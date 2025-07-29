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
        try:
            serper_resp = httpx.post(
                "https://google.serper.dev/search",
                json={
                    "q": termo,
                    "hl": "pt",
                    "gl": "br",
                    "location": "Brazil",
                    "page": 1,
                },
                headers=headers,
                timeout=30,
            )
            serper_data = serper_resp.json()
        except Exception:
            serper_data = {}

        rapid_key = os.getenv("RAPID_API_KEY", "1704232c36msh72debd15f5f3b9ep1ec95ejsn5d9529d788fe")
        rapid_headers = {
            "x-rapidapi-host": "local-business-data.p.rapidapi.com",
            "x-rapidapi-key": rapid_key,
        }
        try:
            rapid_resp = httpx.get(
                "https://local-business-data.p.rapidapi.com/search-in-area",
                params={
                    "query": termo,
                    "lat": lat,
                    "lng": lng,
                    "zoom": 13,
                    "limit": 5,
                    "language": "pt",
                    "region": "br",
                    "extract_emails_and_contacts": "true",
                },
                headers=rapid_headers,
                timeout=30,
            )
            rapid_data = rapid_resp.json()
        except Exception:
            rapid_data = {}
        print(rapid_data)
        return RunResponse(content={"serper": serper_data, "rapid": rapid_data})


class InterpreterAgent(Agent):
    """Fetches leads from Serper Maps and RapidAPI."""

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
        """Collect leads using Serper Maps instead of GPT."""

        serper_key = os.getenv("SERPER_API_KEY", "690002f532f01766edb5037e0a53fd0bc963f6af")
        headers = {"X-API-KEY": serper_key, "Content-Type": "application/json"} if serper_key else {}
        try:
            maps_resp = httpx.post(
                "https://google.serper.dev/maps",
                json={"q": termo, "hl": "pt-br", "ll": f"@{lat},{lng},13z"},
                headers=headers,
                timeout=30,
            )
            maps_data = maps_resp.json()
        except Exception:
            maps_data = {}

        gpt_leads: List[Dict[str, Any]] = []
        for place in maps_data.get("localResults", {}).get("places", []):
            phone = place.get("phoneNumber")
            email = place.get("email")
            if phone and email:
                gpt_leads.append(
                    {
                        "name": place.get("title"),
                        "whatsapp": phone,
                        "emails": email,
                        "address": place.get("address"),
                        "about": "serper_maps",
                    }
                )

        rapid_leads: List[Dict[str, Any]] = []
        for item in rapid_data.get("data", []):
            contacts = item.get("emails_and_contacts", {})
            emails = contacts.get("emails") or []
            phones = contacts.get("phone_numbers") or []
            phone = item.get("phone_number") or (phones[0] if phones else None)
            email = emails[0] if emails else None
            if phone and email:
                rapid_leads.append(
                    {
                        "name": item.get("name"),
                        "whatsapp": phone,
                        "emails": email,
                        "address": item.get("address") or item.get("full_address"),
                        "about": "rapidapi",
                    }
                )

        return RunResponse(content={"leads": gpt_leads + rapid_leads})

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
