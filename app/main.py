from fastapi import FastAPI
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat

from .agents import SearchLeadsWorkflow

# Example chat agent from template
chat_agent = Agent(model=OpenAIChat(id="gpt-4.1-mini"))

app = FastAPI(title="Agno AI Agent")


class Prompt(BaseModel):
    prompt: str


@app.post("/chat")
async def chat(prompt: Prompt):
    """Generate a response using the configured AI agent."""
    run_response = chat_agent.run(prompt.prompt)
    return {"response": run_response.content}


class LeadRequest(BaseModel):
    id_user: str
    termo: str
    num: int
    lat: float
    lng: float


@app.post("/search-leads")
async def search_leads(req: LeadRequest):
    """Main endpoint to search and store leads."""
    workflow = SearchLeadsWorkflow()
    result = workflow.run_workflow(
        id_user=req.id_user,
        termo=req.termo,
        num=req.num,
        lat=req.lat,
        lng=req.lng,
    )
    leads = result.content if result else []
    return {"message": "Leads encontrados com sucesso!", "leads": leads}
