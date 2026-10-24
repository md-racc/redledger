"""Green service: /health /turn. Owner: Dev M. Run: uvicorn server:app --port 8002"""

from agent import GreenAgent
from agentkit import make_agent_app

app = make_agent_app(GreenAgent)
