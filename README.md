# backend-ai-agents

A simple FastAPI project demonstrating how to integrate the [Agno](https://docs.agno.com/introduction/agents) agent framework with [OpenAI](https://platform.openai.com/docs/) using the `gpt-4.1-mini` model.

## Installation

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set your OpenAI API key as an environment variable:

```bash
export OPENAI_API_KEY="YOUR_KEY"
```

## Running the server

Start the FastAPI app with Uvicorn:

```bash
uvicorn app.main:app --reload
```

The API exposes a single `/chat` endpoint that accepts a prompt and returns the model response.

Refer to the [FastAPI installation guide](https://fastapi.tiangolo.com/#installation) for additional details.
