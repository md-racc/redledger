"""Blue service; shared turn lifecycle plus receipt-based /audit, unlocked deterministic gate."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from agentkit import make_agent_app
from agentkit.config import AgentSettings
from agentkit.models import AuditRequest, AuditResponse, GateRequest, GateResponse, TurnRequest
from agentkit.server import bearer_dependency
from audit.agent import AuditAgent
from gate import engine
from gate.playbooks import Playbooks


def extra(app: FastAPI, agent: AuditAgent, settings: AgentSettings) -> None:
    auth = bearer_dependency(settings)
    playbooks = Playbooks(settings)

    @app.post("/gate", response_model=GateResponse, dependencies=[Depends(auth)])
    async def gate(req: GateRequest) -> GateResponse:
        return await engine.decide(req, dry_run=settings.dry_run, extra_hits=tuple(await playbooks.hits(req)), retired=await playbooks.retired(req))

    @app.post("/gate/explain", dependencies=[Depends(auth)])
    async def gate_explain(req: GateRequest):
        return engine.explain(req, extra_hits=tuple(await playbooks.hits(req)), retired=await playbooks.retired(req))

    @app.post("/audit", response_model=AuditResponse, dependencies=[Depends(auth)])
    async def audit(req: AuditRequest) -> AuditResponse:
        result = await agent.run_turn(
            TurnRequest(
                episode_id=req.episode_id,
                day=req.day,
                controller_mode="enforce",
                options={
                    "inputs": req.inputs,
                    **({"lineage": req.lineage.model_dump()} if req.lineage is not None else {}),
                    **({"debrief": req.debrief.model_dump()} if req.debrief is not None else {}),
                },
            )
        )
        outcome = agent.outcome(req.episode_id, req.day)
        return AuditResponse(
            ok=result.ok,
            summary=result.summary,
            report_posted=outcome.report_posted,
            flags_raised=outcome.flags_raised,
        )


app = make_agent_app(AuditAgent, extra_routes=extra)
