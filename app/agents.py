import json
import os
from typing import List, Dict, Any

import httpx
from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.workflow import RunResponse, Workflow
from supabase import create_client, Client


class CollectorAgent(Agent):
    """Collects raw lead data from Serper and Rapid APIs."""

    def run(self, termo: str, lat: float, lng: float) -> RunResponse:
        serper_key = os.getenv("SERPER_API_KEY")
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
                "region": "us",
                "language": "en",
                "coordinates": f"{lat},{lng}",
            },
            headers=rapid_headers,
            timeout=30,
        )
        rapid_data = rapid_resp.json()
        return RunResponse(content={"serper": serper_data, "rapid": rapid_data})


class InterpreterAgent(Agent):
    """Interprets raw search results using GPT-4."""

    def __init__(self) -> None:
        super().__init__(model=OpenAIChat(id="gpt-4o"))

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
            "Você é um especialista em encontrar leads comerciais com número de "
            "WhatsApp e email válidos. Utilize as respostas obtidas das ferramentas "
            "Serper e Rapid. Filtre apenas contatos com telefone (WhatsApp) e email "
            "preenchidos. Utilize estratégias de busca como variações geográficas "
            "e domínios populares (ex: instagram.com, linkedin.com). Nunca retorne "
            "um lead sem telefone e email. Retorne os dados no seguinte JSON "
            "estruturado:\n\n{\n \"leads\": [ {\n  \"name\": \"Nome da empresa ou "
            "contato\",\n  \"whatsapp\": \"Somente números\",\n  \"email\": "
            "\"email válido\",\n  \"address\": \"opcional\",\n  \"summary\": "
            "\"Origem ou observações\"\n } ]\n}"
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
            phone = lead.get("whatsapp")
            email = lead.get("email")
            if phone and email:
                valid.append(lead)
        return RunResponse(content=valid)


class StorageAgent(Agent):
    """Stores leads in Supabase."""

    def __init__(self) -> None:
        super().__init__(model=None)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.client: Client | None = None
        if url and key:
            self.client = create_client(url, key)

    def run(self, id_user: str, leads: List[Dict[str, Any]], lat: float, lng: float) -> RunResponse:
        if not self.client:
            return RunResponse(content={"stored": 0})
        for lead in leads:
            self.client.table("leads").insert(
                {
                    "id_user": id_user,
                    "name": lead.get("name"),
                    "phone": lead.get("whatsapp"),
                    "email": lead.get("email"),
                    "address": lead.get("address"),
                    "summary": lead.get("summary"),
                    "latitude": lat,
                    "longitude": lng,
                }
            ).execute()
        return RunResponse(content={"stored": len(leads)})


class SearchLeadsWorkflow(Workflow):
    """Workflow orchestrating the lead search pipeline."""

    collector = CollectorAgent()
    interpreter = InterpreterAgent()
    validator = ValidatorAgent()
    storage = StorageAgent()

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
        self.storage.run(id_user, valid_leads, lat, lng)
        return RunResponse(content=valid_leads)
