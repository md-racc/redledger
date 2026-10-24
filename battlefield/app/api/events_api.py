"""GET/POST /events and the /ws socket. Owner: Dev Ad."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from agentkit.models import AGENT_EMITTABLE, AgentEventCreate, agent_may_emit

from ..auth import Caller, allow, caller
from ..config import settings
from ..events import bus

router = APIRouter()


@router.get("/events")
async def get_events(episode_id: str, after_id: int = 0, limit: int = Query(500, le=5000), c: Caller = Depends(caller)):
    return await bus.history(episode_id, after_id, limit)


@router.post("/events", status_code=202)
async def post_events(items: list[AgentEventCreate], c: Caller = Depends(allow("red", "green", "blue", operator=False))):
    bad = [i.type for i in items if not agent_may_emit(i.type)]
    if bad:
        raise HTTPException(422, f"agents may only emit {sorted(AGENT_EMITTABLE)} or x.<area>.<name>; got {bad}")
    n = await bus.emit_many(c.episode_id, c.day, c.agent, [i.model_dump() for i in items])  # type: ignore[arg-type]
    return {"accepted": n}


@router.websocket("/ws")
async def ws(websocket: WebSocket, episode_id: str | None = None, token: str | None = None, after_id: int = 0):
    if token != settings.internal_token:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = bus.subscribe(episode_id)
    try:
        if episode_id and after_id is not None:
            for ev in await bus.history(episode_id, after_id, 5000):
                await websocket.send_text(json.dumps(ev))
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20)
                await websocket.send_text(json.dumps(ev))
            except TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(episode_id, q)
