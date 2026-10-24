"""Blue service: /health /gate /audit (/turn exists but is unused). Owner: Dev M.
Run: AGENT_NAME=blue uvicorn server:app --port 8003"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from agentkit import make_agent_app
from agentkit.models import AuditRequest, AuditResponse, GateRequest, GateResponse, TurnRequest
from agentkit.server import bearer_dependency
from audit.agent import AuditAgent
from gate import engine


def extra(app: FastAPI, agent: AuditAgent, settings) -> None:
    auth = bearer_dependency(settings)

    @app.post("/gate", response_model=GateResponse, dependencies=[Depends(auth)])
    async def gate(req: GateRequest) -> GateResponse:
        return await engine.decide(req)

    @app.post("/gate/explain", dependencies=[Depends(auth)])
    async def gate_explain(req: GateRequest):
        return engine.explain(req)

    @app.post("/audit", response_model=AuditResponse, dependencies=[Depends(auth)])
    async def audit(req: AuditRequest) -> AuditResponse:
        res = await agent.run_turn(TurnRequest(episode_id=req.episode_id, day=req.day, controller_mode="enforce"))
        return AuditResponse(ok=res.ok, summary=res.summary, report_posted=res.ok, flags_raised=0)


app = make_agent_app(AuditAgent, extra_routes=extra)
