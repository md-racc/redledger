"""Bearer auth + per-agent route permissions + WebSocket tickets. Owner: Dev Ad.

Two kinds of caller, told apart by the X-Agent header (contracts/agent-service.md "Tokens"):
  - agents: send X-Agent / X-Episode / X-Day (+ X-Tool-Use-Id on writes) and must present their
    OWN token (AGENT_TOKEN_<A>, falling back to the shared AGENT_TOKEN). Another agent's token or
    the operator token for a claimed X-Agent is a 401, audited, so no agent can act or read as
    another. `Caller` carries the headers. Responses to agents hide provenance columns.
  - operator/frontend server: no X-Agent; must present OPERATOR_TOKEN. Sees everything.
(With one shared token every role keeps working; config logs that separation is off.)

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

import structlog
from fastapi import Depends, Header, HTTPException, Request

from . import turns
from .config import settings

log = structlog.get_logger(__name__)

AGENTS = ("red", "green", "blue")
WS_TICKET_TTL_SEC = 60


def token_matches(presented: str | None, expected: str) -> bool:
    """Constant-time token comparison; None never matches."""
    if presented is None:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def _agent_token(agent: str) -> str:
    """The claimed agent's own token, else the shared AGENT_TOKEN (same rule as Settings.token_for;
    resolved here with getattr so a settings stand-in that only has agent_token keeps working)."""
    return getattr(settings, f"agent_token_{agent}", None) or settings.agent_token


def _presented(authorization: str | None) -> str | None:
    return authorization[7:] if authorization is not None and authorization.startswith("Bearer ") else None


def _token_owner(presented: str | None) -> str | None:
    """Which known role a token belongs to ("red" / "green" / "blue" / "operator"), or None. Each
    candidate is compared in constant time; with shared tokens the first match wins (it is only used to
    decide whether a refusal is worth an audit row)."""
    for role in (*AGENTS, "operator"):
        if token_matches(presented, settings.operator_token if role == "operator" else _agent_token(role)):
            return role
    return None


def _authenticate(authorization: str | None, x_agent: str | None) -> None:
    """401 unless the bearer token is the caller's own: the claimed agent's token with X-Agent,
    OPERATOR_TOKEN without. An unknown X-Agent presented with a valid agent token is a 400 (caller)."""
    presented = _presented(authorization)
    if x_agent is None:
        if not token_matches(presented, settings.operator_token):
            raise HTTPException(401, "bad token")
        return
    if x_agent in AGENTS:
        if not token_matches(presented, _agent_token(x_agent)):
            raise HTTPException(401, "bad token")
        return
    if _token_owner(presented) not in AGENTS:
        raise HTTPException(401, "bad token")


REFUSAL_ACTION = "auth.refused"  # operator-only in every agent view (reads.list_audit)


async def _authenticate_audited(request: Request, authorization: str | None, x_agent: str | None, x_episode: str | None, x_day: int | None) -> None:
    """`_authenticate`, plus an audit row when a known caller presents a token that doesn't
    authenticate the X-Agent it claims (one agent posing as another, or the operator token with
    X-Agent). The row is `auth.refused`, hidden from agents: it names whose token was presented.
    Garbage tokens and unknown episodes are only logged, so an unauthenticated request never writes."""
    try:
        _authenticate(authorization, x_agent)
    except HTTPException as e:
        if e.status_code == 401 and x_agent in AGENTS:
            owner = _token_owner(_presented(authorization))
            log.warning("agent_token_mismatch", claimed=x_agent, presented_by=owner or "unknown", path=request.url.path)
            if owner is not None and x_episode is not None and x_day is not None and await _episode_exists(x_episode):
                await _audit_token_refusal(Caller(agent=x_agent, episode_id=x_episode, day=x_day, tool_use_id=None), request, owner)
        raise


async def _episode_exists(episode_id: str) -> bool:
    from . import db  # late: keeps this module importable without a pool

    try:
        return bool(await db.fetchval("SELECT 1 FROM episodes WHERE id=$1", episode_id))
    except Exception:
        log.exception("refusal_episode_lookup_failed", episode_id=episode_id)
        return False


async def _audit_token_refusal(c: Caller, request: Request, presented_by: str) -> None:
    """One operator-only `auth.refused` row (route, claimed agent, whose token; never the token)."""
    from .api import audit  # late: audit imports this module

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    try:
        await audit.record(
            c, REFUSAL_ACTION, {"route": f"{request.method} {path}"}, {"error": "token does not authenticate X-Agent", "presented_by": presented_by}, 401
        )
    except Exception:
        log.exception("refusal_audit_failed", agent=c.agent, episode_id=c.episode_id, path=path)


async def bearer(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent: str | None = Header(default=None, alias="X-Agent"),
    x_episode: str | None = Header(default=None, alias="X-Episode"),
    x_day: int | None = Header(default=None, alias="X-Day"),
) -> None:
    """Dependency for operator-only routes: OPERATOR_TOKEN and no X-Agent. A known token presented
    for a claimed X-Agent it doesn't authenticate is audited like on agent routes."""
    await _authenticate_audited(request, authorization, x_agent, x_episode, x_day)
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


async def caller(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent: str | None = Header(default=None, alias="X-Agent"),
    x_episode: str | None = Header(default=None, alias="X-Episode"),
    x_day: int | None = Header(default=None, alias="X-Day"),
    x_tool_use_id: str | None = Header(default=None, alias="X-Tool-Use-Id"),
) -> Caller:
    await _authenticate_audited(request, authorization, x_agent, x_episode, x_day)
    if x_agent is not None:
        if x_agent not in AGENTS:
            raise HTTPException(400, f"unknown X-Agent {x_agent}")
        if x_episode is None or x_day is None:
            raise HTTPException(400, "agents must send X-Episode and X-Day")
        if x_episode.startswith("replay_"):  # control.REPLAY_PREFIX: replays are event-only, never agent-facing
            raise HTTPException(403, "agents may not act in replay episodes")
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            if not x_tool_use_id:
                raise HTTPException(400, "writes require X-Tool-Use-Id")
            if not turns.may_write(x_episode, x_agent, x_day):
                c = Caller(agent=x_agent, episode_id=x_episode, day=x_day, tool_use_id=x_tool_use_id)
                await _audit_no_turn(c, request)
                raise turns.NoActiveTurnError(turns.NO_ACTIVE_TURN)
    return Caller(agent=x_agent, episode_id=x_episode, day=x_day, tool_use_id=x_tool_use_id)


async def _audit_no_turn(c: Caller, request: Request) -> None:
    """Audit an agent write refused for lack of an active turn (an orphaned or timed-out turn)."""
    await _audit_refusal(c, request, {"error": turns.NO_ACTIVE_TURN}, 409)


async def _audit_refusal(c: Caller, request: Request, result: dict, status: int) -> None:
    """Best effort: the refusal must stand even if the audit write fails. Never records a token."""
    from .api import audit  # late: audit imports this module

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    try:
        await audit.record(c, f"{request.method} {path}", dict(request.path_params), result, status)
    except Exception:
        log.exception("refusal_audit_failed", agent=c.agent, episode_id=c.episode_id, path=path, status=status)


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
