import json
import os
import re
from typing import List, Dict, Any

import httpx
from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.workflow import RunResponse, Workflow
from supabase import create_client, Client


class CollectorAgent(Agent):
    """Collects raw lead data from Serper and Rapid APIs."""

    def run(self, termo: str, lat: float, lng: float) -> RunResponse:
        serper_key = os.getenv("SERPER_API_KEY","690002f532f01766edb5037e0a53fd0bc963f6af")
        headers = {"X-API-KEY": serper_key} if serper_key else {}
        serper_resp = httpx.post(
            "https://google.serper.dev/search",
            json={"q": termo, "hl": "pt", "gl": "br", "location": "Brazil", "page": 1},
            headers=headers,
            timeout=30,
        )
        serper_data = serper_resp.json()

        rapid_key = os.getenv("RAPID_API_KEY", "1704232c36msh72debd15f5f3b9ep1ec95ejsn5d9529d788fe")
        rapid_headers = {
            "x-rapidapi-host": "local-business-data.p.rapidapi.com",
            "x-rapidapi-key": rapid_key,
        }
        rapid_resp = httpx.get(
            "https://local-business-data.p.rapidapi.com/autocomplete",
            params={
                "query": termo,
                "region": "br",
                "language": "pt",
                "coordinates": f"{lat},{lng}",
            },
            headers=rapid_headers,
            timeout=30,
        )
        rapid_data = rapid_resp.json()
        print(rapid_data)
        return RunResponse(content={"serper": serper_data, "rapid": rapid_data})


class InterpreterAgent(Agent):
    """Interprets raw search results using GPT-4."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with optional Agent settings."""
        super().__init__(model=OpenAIChat(id="gpt-4.1-mini"), **kwargs)

    def run(
        self,
        serper_data: Dict[str, Any],
        rapid_data: Dict[str, Any],
        termo: str,
        num: int,
        lat: float,
        lng: float,
    ) -> RunResponse:
        system_prompt = (
            "Você é um especialista em encontrar leads comerciais. "
            "Sempre forneça somente contatos com e-mail válido e telefone real, nunca inventado. "
            "Utilize as respostas das ferramentas Serper e Rapid para filtrar apenas leads que possuam "
            "telefone e e-mail preenchidos e válidos. Limite-se a empresas localizadas dentro de um raio "
            "máximo de 50 quilômetros da latitude e longitude informadas, sem jamais contrariar esse requisito. "
            "Use também domínios populares como instagram.com, linkedin.com e maps.google.com. "
            "Retorne os dados no seguinte JSON estruturado:\n\n{\n \"leads\": [ {\n  \"name\": \"Nome da empresa ou contato\",\n  \"whatsapp\": \"telefone válido\",\n  \"email\": \"email válido\",\n  \"address\": \"opcional\",\n  \"summary\": \"Origem ou observações\"\n } ]\n}"
        )
        user_prompt = (
            f"Termo: {termo}\n\nEncontre pelo menos {num} leads comerciais próximos "
            f"de latitude {lat} e longitude {lng}."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"SERPER: {json.dumps(serper_data)}"},
            {"role": "system", "content": f"RAPID: {json.dumps(rapid_data)}"},
            {"role": "user", "content": user_prompt},
        ]
        response = super().run(messages=messages)
        try:
            leads = json.loads(response.content)
        except Exception:
            leads = None
        return RunResponse(content=leads)


class ValidatorAgent(Agent):
    """Validates the structure of lead data."""

    def run(self, leads: Dict[str, Any]) -> RunResponse:
        valid: List[Dict[str, Any]] = []
        if not leads or "leads" not in leads:
            return RunResponse(content=valid)
        for lead in leads.get("leads", []):
            phone = lead.get("whatsapp") or lead.get("phone")
            email = lead.get("email") or lead.get("emails")
            digits = re.sub(r"\D", "", phone or "")
            email_valid = bool(email) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(email))
            phone_valid = bool(digits) and len(digits) >= 8
            if phone_valid and email_valid:
                valid.append(lead)
        return RunResponse(content=valid)


class FormatterAgent(Agent):
    """Formats leads to match Supabase table structure."""

    def run(self, leads: List[Dict[str, Any]]) -> RunResponse:
        formatted: List[Dict[str, Any]] = []
        for lead in leads:
            formatted.append(
                {
                    "name": lead.get("name"),
                    "phone": lead.get("whatsapp") or lead.get("phone"),
                    "emails": lead.get("emails"),
                    "address": lead.get("address"),
                    "about": lead.get("about"),
                }
            )
        return RunResponse(content=formatted)

class StorageAgent(Agent):
    """Stores leads in Supabase."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with optional Agent settings."""
        super().__init__(model=OpenAIChat(id="gpt-4.1-mini"), **kwargs)
        url = os.getenv("SUPABASE_URL", "https://tzoobaegujxeoozeasoh.supabase.co")
        key = os.getenv("SUPABASE_KEY","eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR6b29iYWVndWp4ZW9vemVhc29oIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0ODM3NjM2NCwiZXhwIjoyMDYzOTUyMzY0fQ.EPQhPtkCEQVbG0ZDEellSlAAmh5_1MT4M_xg_K-Lh2I")
        self.client: Client | None = None
        if url and key:
            self.client = create_client(url, key)

    def run(self, id_user: str, leads: List[Dict[str, Any]], lat: float, lng: float) -> RunResponse:
        if not self.client:
            return RunResponse(content={"stored": 0})

        payload = [
            {
                "id_user": id_user,
                "name": lead.get("name"),
                "phone": lead.get("phone"),
                "emails": lead.get("emails"),
                "address": lead.get("address"),
                "about": lead.get("about"),
            }
            for lead in leads
        ]
        if payload:
            self.client.table("leads").insert(payload).execute()
        return RunResponse(content={"stored": len(payload)})


class SearchLeadsWorkflow(Workflow):
    """Workflow orchestrating the lead search pipeline."""

    collector = CollectorAgent(monitoring=True)
    interpreter = InterpreterAgent(monitoring=True)
    validator = ValidatorAgent(monitoring=True)
    formatter = FormatterAgent(monitoring=True)
    storage_agent = StorageAgent(monitoring=True)

    def run(
        self,
        id_user: str,
        termo: str,
        num: int,
        lat: float,
        lng: float,
    ) -> RunResponse:
        collected = self.collector.run(termo, lat, lng).content
        leads_raw = self.interpreter.run(
            collected["serper"], collected["rapid"], termo, num, lat, lng
        ).content
        valid_leads = self.validator.run(leads_raw).content
        formatted_leads = self.formatter.run(valid_leads).content
        self.storage_agent.run(id_user, formatted_leads, lat, lng)
        return RunResponse(content=formatted_leads)
