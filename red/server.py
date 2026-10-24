"""Red service: /health /turn /schemes. Owner: Dev Al. Run: uvicorn server:app --port 8001"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from agent import RedAgent
from agentkit import make_agent_app
from agentkit.server import bearer_dependency
from schemes import SCHEMES


def extra(app: FastAPI, agent, settings) -> None:
    @app.get("/schemes", dependencies=[Depends(bearer_dependency(settings))])
    async def schemes():
        return [s.catalog().model_dump() for s in SCHEMES.values()]


app = make_agent_app(RedAgent, extra_routes=extra)
