"""Bearer auth + per-agent route permissions + WebSocket tickets. Owner: Dev Ad.

Two kinds of caller, told apart by the X-Agent header and each with its own token:
  - agents: send X-Agent / X-Episode / X-Day (+ X-Tool-Use-Id on writes) and must present
    AGENT_TOKEN. `Caller` is injected into handlers and carries them. Responses to agents hide
    provenance columns.
  - operator/frontend server: no X-Agent; must present OPERATOR_TOKEN. Sees everything.
The token must match the expected token for the role, else 401. (With the legacy single
INTERNAL_TOKEN both are equal and both roles keep working; config logs a warning.)

Permissions are declared per route with `allow("red", "green")`. A route with no `allow` is
operator-only when it is a control-plane route, or all-agents when it is a read route.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from .config import settings

AGENTS = ("red", "green", "blue")
WS_TICKET_TTL_SEC = 60


def token_matches(presented: str | None, expected: str) -> bool:
    """Constant-time token comparison; None never matches."""
    if presented is None:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def _authenticate(authorization: str | None, x_agent: str | None) -> None:
    """401 unless the bearer token is the one for the caller's role (X-Agent present = agent)."""
    expected = settings.agent_token if x_agent is not None else settings.operator_token
    presented = authorization[7:] if authorization is not None and authorization.startswith("Bearer ") else None
    if not token_matches(presented, expected):
        raise HTTPException(401, "bad token")


def bearer(authorization: str | None = Header(default=None), x_agent: str | None = Header(default=None, alias="X-Agent")) -> None:
    """Dependency for operator-only routes: OPERATOR_TOKEN and no X-Agent."""
    _authenticate(authorization, x_agent)
    if x_agent is not None:
        raise HTTPException(403, "operator only")


@dataclass
class Caller:
    agent: str | None  # None = operator/frontend
    episode_id: str | None
    day: int | None
    tool_use_id: str | None

    @property
    def is_agent(self) -> bool:
        return self.agent is not None

    @property
    def hide(self) -> bool:
        return self.is_agent


def caller(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent: str | None = Header(default=None, alias="X-Agent"),
    x_episode: str | None = Header(default=None, alias="X-Episode"),
    x_day: int | None = Header(default=None, alias="X-Day"),
    x_tool_use_id: str | None = Header(default=None, alias="X-Tool-Use-Id"),
) -> Caller:
    _authenticate(authorization, x_agent)
    if x_agent is not None:
        if x_agent not in AGENTS:
            raise HTTPException(400, f"unknown X-Agent {x_agent}")
        if x_episode is None or x_day is None:
            raise HTTPException(400, "agents must send X-Episode and X-Day")
        if x_episode.startswith("replay_"):  # control.REPLAY_PREFIX: replays are event-only, never agent-facing
            raise HTTPException(403, "agents may not act in replay episodes")
        if request.method in ("POST", "PATCH", "PUT", "DELETE") and not x_tool_use_id:
            raise HTTPException(400, "writes require X-Tool-Use-Id")
    return Caller(agent=x_agent, episode_id=x_episode, day=x_day, tool_use_id=x_tool_use_id)


def allow(*agents: str, operator: bool = True):
    """Dependency: only these agents (and optionally the operator) may call the route."""

    def dep(c: Caller = Depends(caller)) -> Caller:
        if c.is_agent:
            if c.agent not in agents:
                raise HTTPException(403, f"{c.agent} may not call this route")
        elif not operator:
            raise HTTPException(403, "agents only")
        return c

    return dep


def agent_episode(c: Caller, episode_id_query: str | None = None) -> str:
    """Resolve which episode a request is about: agents from header, operator from query."""
    if c.is_agent:
        return c.episode_id  # type: ignore[return-value]
    if episode_id_query is None:
        raise HTTPException(400, "episode_id required")
    return episode_id_query


# ---------- WebSocket tickets ----------
# `<scope>.<exp>.<nonce>.<sig>`: scope = episode_id or "*", exp = unix seconds, nonce = 16 random
# lowercase hex chars, sig = hex HMAC-SHA256(key=OPERATOR_TOKEN, msg=f"{scope}|{exp}|{nonce}").
# Single use, in-process only. The nonce makes two tickets minted in the same second for the same
# scope distinct, so each works once. Every part must be in canonical form (no leading
# zeros/sign/whitespace/underscores in exp, lowercase hex nonce and sig), and the used-set is
# keyed by the canonical `scope|exp|nonce`, so one ticket has exactly one spelling and cannot be
# replayed under another. Old 3-part tickets are rejected (they lived 60 s; nothing to migrate).

TICKET_SCOPE_RE = re.compile(r"\*|[A-Za-z0-9_-]{1,64}")
_TICKET_EXP_RE = re.compile(r"[1-9][0-9]{0,11}")
_TICKET_NONCE_RE = re.compile(r"[0-9a-f]{16}")
_TICKET_SIG_RE = re.compile(r"[0-9a-f]{64}")

_used_tickets: dict[str, int] = {}  # canonical f"{scope}|{exp}|{nonce}" -> exp, pruned on every check


def _ticket_sig(scope: str, exp: int, nonce: str) -> str:
    return hmac.new(settings.operator_token.encode(), f"{scope}|{exp}|{nonce}".encode(), hashlib.sha256).hexdigest()


def issue_ws_ticket(episode_id: str | None, *, now: float | None = None) -> tuple[str, int]:
    """Mint a ticket for one WS connection to `episode_id` (None = every episode). Returns (ticket, exp).

    Raises ValueError if `episode_id` is not a valid ticket scope (it could never verify).
    """
    scope = episode_id or "*"
    if not TICKET_SCOPE_RE.fullmatch(scope):
        raise ValueError(f"episode_id must match {TICKET_SCOPE_RE.pattern}")
    exp = int(now if now is not None else time.time()) + WS_TICKET_TTL_SEC
    nonce = secrets.token_hex(8)
    return f"{scope}.{exp}.{nonce}.{_ticket_sig(scope, exp, nonce)}", exp


def verify_ws_ticket(ticket: str | None, episode_id: str | None, *, now: float | None = None) -> bool:
    """True once per valid, unexpired ticket whose scope is "*" or equals `episode_id`."""
    t = int(now if now is not None else time.time())
    for k in [k for k, exp in _used_tickets.items() if exp < t]:
        del _used_tickets[k]
    if not ticket:
        return False
    parts = ticket.split(".")
    if len(parts) != 4:
        return False
    scope, exp_s, nonce, sig = parts
    if not (TICKET_SCOPE_RE.fullmatch(scope) and _TICKET_EXP_RE.fullmatch(exp_s) and _TICKET_NONCE_RE.fullmatch(nonce) and _TICKET_SIG_RE.fullmatch(sig)):
        return False
    exp = int(exp_s)
    if not hmac.compare_digest(sig.encode(), _ticket_sig(scope, exp, nonce).encode()):
        return False
    key = f"{scope}|{exp}|{nonce}"
    if exp < t or key in _used_tickets:
        return False
    if scope != "*" and scope != episode_id:
        return False
    _used_tickets[key] = exp
    return True
