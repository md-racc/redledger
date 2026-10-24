"""GET/POST /events, POST /ws/ticket and the /ws socket. Owner: Dev Ad.

Agents emit events, never read them (AGENTS.md invariant 11): GET /events and /ws are
operator-only. The browser gets a short-lived single-use ticket via the frontend server.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from agentkit.models import AGENT_EMITTABLE, AgentEventCreate, agent_may_emit

from ..auth import Caller, allow, bearer, issue_ws_ticket, token_matches, verify_ws_ticket
from ..config import settings
from ..events import bus

router = APIRouter()


class WsTicketRequest(BaseModel):
    episode_id: str | None = None


@router.get("/events", dependencies=[Depends(bearer)])
async def get_events(episode_id: str, after_id: int = 0, limit: int = Query(500, le=5000)):
    return await bus.history(episode_id, after_id, limit)


@router.post("/events", status_code=202)
async def post_events(items: list[AgentEventCreate], c: Caller = Depends(allow("red", "green", "blue", operator=False))):
    bad = [i.type for i in items if not agent_may_emit(i.type)]
    if bad:
        raise HTTPException(422, f"agents may only emit {sorted(AGENT_EMITTABLE)} or x.<area>.<name>; got {bad}")
    n = await bus.emit_many(c.episode_id, c.day, c.agent, [i.model_dump() for i in items])  # type: ignore[arg-type]
    return {"accepted": n}


@router.post("/ws/ticket", dependencies=[Depends(bearer)])
async def ws_ticket(body: WsTicketRequest | None = None):
    try:
        ticket, exp = issue_ws_ticket(body.episode_id if body else None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"ticket": ticket, "expires_at": datetime.fromtimestamp(exp, UTC).isoformat()}


@router.websocket("/ws")
async def ws(websocket: WebSocket, episode_id: str | None = None, token: str | None = None, ticket: str | None = None, after_id: int = 0):
    # operator token (curl/debug) first so a redundant ticket is not burned; else a single-use ticket
    # accept first, then close: a close before accept is an HTTP 403 handshake rejection and the
    # browser only sees 1006; the contract promises close code 4401.
    await websocket.accept()
    if not (token_matches(token, settings.operator_token) or verify_ws_ticket(ticket, episode_id)):
        await websocket.close(code=4401)
        return
    # subscribe before reading history so nothing emitted in between is missed; anything emitted in
    # that window is then both in history and queued live, so live frames at or below the history
    # high-water mark are dropped (each event reaches the client once).
    q = bus.subscribe(episode_id)
    try:
        sent_upto = 0
        if episode_id and after_id is not None:
            sent_upto = after_id
            for ev in await bus.history(episode_id, after_id, 5000):
                await websocket.send_text(json.dumps(ev))
                sent_upto = max(sent_upto, ev["id"])
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20)
                if isinstance(ev.get("id"), int) and ev["id"] <= sent_upto:
                    continue
                await websocket.send_text(json.dumps(ev))
            except TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(episode_id, q)
