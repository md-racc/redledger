"""Offline diagnostics only: never start a session, listener, model or Ledger request."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

from pydantic import ValidationError

from agentkit import ctx
from agentkit.config import AgentSettings
from agentkit.sync import TurnLock

from . import tools
from .models import AuditSession, Snapshot

LIVE_BLOCKERS = (
    "blue_session_ids_unverified",
    "sdk_invocation_binding_unverified",
    "blue_owner_loop_safety_unverified",
    "blue_narration_ownership_unverified",
    "nonblocking_bridge_unverified",
    "live_audit_disabled",
)
PARAMETERS = {
    "benford_check": {},
    "crs_identity_check": {},
    "day_activity": {},
    "freeze_vendor": {"vendor_id": "string", "finding_ids": "array"},
    "post_report": {},
    "raise_flag": {"finding_id": "string"},
    "vendor_dedupe": {},
}


@dataclass(frozen=True)
class Readiness:
    sdk_available: bool
    reason_codes: tuple[str, ...]
    ready: Literal[False] = False


def live_readiness(*, sdk_available: bool = False) -> Readiness:
    """Availability is not proof. No probe, SDK import or environment bypass here."""
    return Readiness(sdk_available, (() if sdk_available else ("sdk_unavailable",)) + LIVE_BLOCKERS)


def schema_matches(name: str, schema: Any) -> bool:
    """Check the complete public argument surface without publishing unknown fields."""
    expected = PARAMETERS.get(name)
    if expected is None or not isinstance(schema, Mapping):
        return False
    properties = schema.get("properties")
    required = schema.get("required", ())
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, Mapping)
        or set(properties) != set(expected)
        or not isinstance(required, (list, tuple))
        or not all(isinstance(key, str) for key in required)
        or sorted(required) != sorted(expected)
    ):
        return False
    for key, kind in expected.items():
        item = properties[key]
        if not isinstance(item, Mapping) or item.get("type") != kind:
            return False
        if kind == "array" and (not isinstance(item.get("items"), Mapping) or item["items"].get("type") != "string"):
            return False
    return True


async def inspect_registry(agent: Any) -> dict[str, Any]:
    """Build the actual shared/SDK registry, not a running MCP server or session IDs."""
    try:
        server = agent._mcp_server()
    except ImportError:
        return {"status": "sdk_unavailable", "tools": []}
    except Exception:
        return {"status": "registry_error", "tools": []}
    try:
        registered = {item.name: item for item in server.tools}
        rows = [{"name": n, "parameters": p, "schema_matches": schema_matches(n, registered[n].input_schema)} for n, p in PARAMETERS.items() if n in registered]
        rejected = False
        # If validation regresses, no turn is bound here: the shared bridge cannot run.
        try:
            await registered["day_activity"].handler({"_tool_use_id": "offline-untrusted", "invocation": "offline-untrusted"})
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_context=False)
            rejected = (
                len(errors) == 2 and all(e["type"] == "extra_forbidden" for e in errors) and {e["loc"] for e in errors} == {("_tool_use_id",), ("invocation",)}
            )
        except Exception:
            pass
        valid = len(server.tools) == len(PARAMETERS) and set(registered) == set(PARAMETERS) and all(r["schema_matches"] for r in rows) and rejected
        return {"status": "registered" if valid else "schema_mismatch", "tools": rows, "extra_metadata_rejected": rejected}
    except Exception:
        return {"status": "registry_error", "tools": []}


def _offline_agent() -> Any:
    from .agent import AuditAgent

    # Explicit dummy values: neither .env nor ambient provider/agent configuration is used.
    settings = AgentSettings(
        AGENT_NAME="blue",
        BATTLEFIELD_URL="http://offline.invalid",
        BLUE_URL="http://offline.invalid",
        AGENT_TOKEN="offline-only",
        FACTORY_API_KEY="",
        DROID_MODEL="",
        DROID_REASONING="",
        DRY_RUN=True,
        TURN_TIMEOUT_SEC=21,
        GATE_TIMEOUT_SEC=1,
        ESCALATION_TIMEOUT_SEC=1,
        HTTP_TIMEOUT_SEC=1,
        LOG_LEVEL="error",
        PORT=0,
        _env_file=None,
    )
    return AuditAgent(settings)


class _ProbeEmitter:
    """In-memory sink only: shared bridge narration must never reach EventEmitter/HTTP."""

    def __init__(self) -> None:
        self.calls = self.results = 0

    def tool_call(self, *args: Any) -> None:
        self.calls += 1

    def tool_result(self, *args: Any) -> None:
        self.results += 1


async def inspect_bridge(agent: Any) -> dict[str, bool | str]:
    """Exercise shared _offload unchanged with a pure tool; clients never send HTTP."""
    from agentkit.models import TurnRequest

    marker = "offline-marker-not-sdk-metadata"
    req = TurnRequest(episode_id="offline", day=1, controller_mode="off")
    session = AuditSession("offline", 1, False, time.monotonic() + 5, snapshot=Snapshot("offline", 1), tool_lock=TurnLock())
    ledger, emitter = object(), _ProbeEmitter()
    bindings = ctx.bind(ledger, emitter, req)
    session_token, invocation_token = tools.SESSION.set(session), tools.INVOCATION.set(marker)
    heartbeat: list[bool] = []
    owner_loop = asyncio.get_running_loop()
    timer = owner_loop.call_later(0.01, heartbeat.append, True)

    async def harmless(**kwargs: Any) -> str:
        await asyncio.sleep(0.05)  # Bounded yield on the worker loop, not a busy wait.
        invocation = ctx.invocation()
        copied_session = tools.SESSION.get()
        return json.dumps(
            {
                "shared_turn_bound": ctx.turn() is req,
                "shared_ledger_rebound": ctx.ledger() is not ledger,
                "shared_emitter_bound": ctx.emitter() is not None,
                "blue_session_propagated": copied_session is session,
                "blue_invocation_propagated": tools.INVOCATION.get() == marker,
                "blue_tool_lock_shared": copied_session is not None and copied_session.tool_lock is session.tool_lock,
                "worker_on_owner_loop": asyncio.get_running_loop() is owner_loop,
                "shared_invocation_bound": invocation is not None,
                "shared_invocation_source": invocation.source if invocation else "unbound",
                "shared_invocation_verified": bool(invocation and invocation.verified),
                "shared_invocation_id_distinct_from_blue_marker": bool(invocation and invocation.tool_use_id != marker),
                "internal_id_kwarg_injected": "_tool_use_id" in kwargs,
            }
        )

    harmless._rl_tool = ("offline_context_probe", "Pure offline probe")
    try:
        result = json.loads(agent._offload(harmless)())
        result["shared_narration_pair_recorded"] = emitter.calls == emitter.results == 1
        result["owner_heartbeat_during_call"] = bool(heartbeat)
        await asyncio.sleep(0.02)
        result["owner_heartbeat_after_call"] = bool(heartbeat)
        return result
    finally:
        timer.cancel()
        tools.INVOCATION.reset(invocation_token)
        tools.SESSION.reset(session_token)
        ctx.unbind(bindings)


async def offline_report() -> dict[str, Any]:
    agent = _offline_agent()
    registry = await inspect_registry(agent)
    sdk_available = registry["status"] in {"registered", "schema_mismatch"}
    versions = {}
    for package in ("droid-sdk", "mcp"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return {
        **asdict(live_readiness(sdk_available=sdk_available)),
        "versions": versions,
        "registry": registry,
        "session_tool_ids_verified": False,
        "authenticated_invocation_verified": False,
        "bridge": await inspect_bridge(agent),
    }


def main() -> None:
    """Exit zero means diagnostics completed, never that live audit is ready."""
    print(json.dumps(asyncio.run(offline_report()), sort_keys=True))


if __name__ == "__main__":
    main()
