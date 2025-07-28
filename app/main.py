from fastapi import FastAPI
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat

# Initialize the agent using OpenAI's GPT-4.1-mini model
chat_agent = Agent(model=OpenAIChat(id="gpt-4.1-mini"))

app = FastAPI(title="Agno AI Agent")

class Prompt(BaseModel):
    prompt: str

@app.post("/chat")
async def chat(prompt: Prompt):
    """Generate a response using the configured AI agent."""
    run_response = chat_agent.run(prompt.prompt)
    return {"response": run_response.content}
