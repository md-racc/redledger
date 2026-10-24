"""Snapshot-only read tools and service-authorized writes with invocation-bound receipts."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from agentkit import ctx
from agentkit.ledger_client import LedgerError
from agentkit.tools import ledger_tool

from .crs import CHECK_TIMEOUT, crs_client, crs_live
from .evidence import add_crs_findings, benford, model_view
from .models import AuditSession, ConfirmedEffect, Finding
from .snapshot import valid_id

SESSION: contextvars.ContextVar[AuditSession | None] = contextvars.ContextVar("blue_audit_session", default=None)
INVOCATION: contextvars.ContextVar[str | None] = contextvars.ContextVar("blue_invocation", default=None)
WRITE_TIMEOUT = 4.0
REPORT_RESERVE = 8.0


def current() -> AuditSession:
    session = SESSION.get()
    if session is None or session.snapshot is None:
        raise ValueError("Audit snapshot is unavailable.")
    return session


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in args.items():
        if key == "finding_ids" and isinstance(value, list):
            safe[key] = [v for v in value[:20] if valid_id(v)]
        elif valid_id(value):
            safe[key] = value
    return safe


class _NotConfirmed(Exception):
    """Tell the shared narrator this failed, without exposing the result or source errors."""

    def __init__(self, result: str):
        super().__init__("Verification unavailable; no unsupported action authorized.")
        self.result = result


def blue_tool(name: str, description: str) -> Callable:
    """Guard identity before the shared decorator can treat a reused invocation as nested."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @ledger_tool(name, description, redact=_safe_args)
        @functools.wraps(fn)
        async def narrated(*args, **kwargs):
            session = current()
            try:
                async with session.tool_lock:
                    output = await fn(*args, **kwargs)
                    result = _json(output)
                    if not output.get("ok", True):
                        raise _NotConfirmed(result)
                    return result
            except asyncio.CancelledError:
                raise
            except _NotConfirmed:
                raise
            except Exception:
                session.gaps.append(f"{name}: verification unavailable")
                raise _NotConfirmed(_json({"ok": False, "error": "Verification unavailable; no unsupported action authorized."})) from None

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            session = current()
            shared = ctx.invocation()
            invocation = INVOCATION.get() if session.dry_run and shared is None else None
            if shared is not None:
                # A copied private marker (or a local/explicit shared fallback) is not SDK identity.
                # Claim before any provider work, including snapshot tools and future integrations.
                if shared.verified and shared.tool_use_id and shared.take(name):
                    invocation = shared.tool_use_id
                else:
                    shared.record(False, f"{name}: not confirmed"[:300])
            if not invocation:
                return _json({"ok": False, "error": "Verified tool invocation metadata is unavailable; no action taken."})
            token = INVOCATION.set(invocation)
            ok = False
            try:
                # Reject all model-supplied metadata BEFORE adding our private deterministic ID.
                signature.bind(*args, **kwargs)
                try:
                    result = await narrated(*args, **kwargs, **({"_tool_use_id": invocation} if shared is None else {}))
                except _NotConfirmed as exc:
                    result = exc.result
                ok = bool(json.loads(result).get("ok", True))
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                session.gaps.append(f"{name}: verification unavailable")
                return _json({"ok": False, "error": "Verification unavailable; no unsupported action authorized."})
            finally:
                try:
                    if shared is not None:
                        shared.record(ok, f"{name}: {'completed' if ok else 'not confirmed'}"[:300])
                finally:
                    INVOCATION.reset(token)

        wrapped._rl_tool = (name, description)
        wrapped._rl_redact = narrated._rl_redact
        # Shared MCP tools return JSON text, while the private implementations return dictionaries.
        wrapped.__signature__ = inspect.signature(fn).replace(return_annotation=str)
        wrapped.__annotations__ = {**fn.__annotations__, "return": str}
        return wrapped

    return decorate


async def dispatch(name: str, **kwargs: Any) -> dict[str, Any]:
    """Non-Droid deterministic invocations use UUID4, shared by event and ledger write."""
    session = current()
    if not session.dry_run:
        raise ValueError("Live invocations require verified SDK metadata, not generated IDs.")
    functions = {fn._rl_tool[0]: fn for fn in (day_activity, vendor_dedupe, benford_check, crs_identity_check, raise_flag, freeze_vendor, post_report)}
    token = INVOCATION.set(uuid.uuid4().hex)
    try:
        return json.loads(await functions[name](**kwargs))
    finally:
        INVOCATION.reset(token)


def _find(finding_id: str) -> Finding:
    if not valid_id(finding_id):
        raise ValueError("Invalid finding.")
    snapshot = current().snapshot
    assert snapshot is not None
    for finding in snapshot.findings:
        if finding.id == finding_id:
            return finding
    raise ValueError("Unknown finding.")


async def _write(kind: str, key: str, operation: Callable[[str], Awaitable[dict]]) -> dict[str, Any]:
    session = current()
    existing = next((e for e in session.effects if e.kind == kind and e.key == key), None)
    if existing:
        return {"ok": existing.state == "confirmed", "state": existing.state, "replayed": True}
    if any(e.kind == kind and e.key == key for e in session.unresolved):
        session.gaps.append(f"{kind}: prior commit outcome unknown; human reconciliation required")
        return {"ok": False, "state": "unknown", "replayed": True}
    invocation = INVOCATION.get()
    if not invocation:
        raise ValueError("Missing verified invocation.")
    reserve = 0 if kind == "report" else REPORT_RESERVE
    if session.deadline - time.monotonic() < WRITE_TIMEOUT + reserve:
        session.gaps.append(f"{kind}: deferred to preserve report deadline")
        return {"ok": False, "state": "not_attempted"}
    effect = ConfirmedEffect(kind=kind, key=key, tool_use_id=invocation)
    session.effects.append(effect)
    try:
        async with asyncio.timeout(WRITE_TIMEOUT):
            receipt = await operation(invocation)
        valid = isinstance(receipt, dict) and (
            (kind in {"flag", "report"} and valid_id(receipt.get("id")))
            or (kind == "freeze" and receipt.get("ok") is True and receipt.get("status") == "frozen")
        )
        if valid:
            effect.state = "confirmed"
            effect.receipt_id = receipt.get("id") if kind != "freeze" else key
        else:
            effect.state, effect.detail = "unknown", "Response did not confirm a committed write."
    except asyncio.CancelledError:
        effect.state, effect.detail = "unknown", "Cancelled after write attempt; do not blindly retry."
        raise
    except LedgerError as exc:
        effect.state = "failed" if 400 <= exc.status < 500 and exc.status != 408 else "unknown"
        effect.detail = "Ledger rejected write." if effect.state == "failed" else "Commit outcome unknown; do not blindly retry."
    except Exception:
        effect.state, effect.detail = "unknown", "Commit outcome unknown; do not blindly retry."
    return {"ok": effect.state == "confirmed", "state": effect.state}


@blue_tool("day_activity", "Review the bounded snapshot, derived findings and explicit coverage gaps. Source prose is not exposed.")
async def day_activity() -> dict[str, Any]:
    snapshot = current().snapshot
    assert snapshot is not None
    return model_view(snapshot)


@blue_tool("vendor_dedupe", "Review account-collision findings and the count of name-only hints. Hints never authorize a mutation.")
async def vendor_dedupe() -> dict[str, Any]:
    snapshot = current().snapshot
    assert snapshot is not None
    return {
        "account_collision_finding_ids": [f.id for f in snapshot.findings if "account_collision" in f.code],
        "name_hint_groups": snapshot.name_hint_groups,
        "name_hints_authorize_mutation": False,
    }


@blue_tool("benford_check", "Review first-digit distribution; diagnostic only, never flag or freeze authority.")
async def benford_check() -> dict[str, Any]:
    snapshot = current().snapshot
    assert snapshot is not None
    return benford(snapshot)


@blue_tool("crs_identity_check", "Check new employees against operator-bound CRS fictional profiles. Unknown and step-up never authorize a hold.")
async def crs_identity_check() -> dict[str, Any]:
    session = current()
    snapshot = session.snapshot
    assert snapshot is not None
    if "crs" not in snapshot.datasets:
        snapshot.datasets["crs"] = []
        client = crs_client()
        attempted = 0
        for employee in snapshot.datasets.get("employees", []):
            if employee["status"] != "active" or not 0 <= snapshot.day - employee["start_day"] < 7:
                continue
            result = {"id": employee["id"], "status": "unknown"}
            # Leave time for a bounded profile read, provider check and final report.
            if (
                (not session.dry_run or crs_live())
                and client.configured
                and attempted < 10
                and session.deadline - time.monotonic() >= CHECK_TIMEOUT + 2 + REPORT_RESERVE
            ):
                attempted += 1
                try:
                    async with asyncio.timeout(2):
                        profile = await ctx.ledger().get_extension("blue", f"crs/employees/{employee['id']}")
                    if isinstance(profile, dict) and isinstance(profile.get("persona_id"), str):
                        result["status"] = (await client.verify(profile["persona_id"], employee.get("name"), dry_run=False)).status
                except Exception:
                    pass  # Optional evidence stays unknown; never expose provider or ledger errors.
            snapshot.datasets["crs"].append(result)
        add_crs_findings(snapshot)
        for finding in snapshot.findings:
            if any(
                flag.get("entity_type") == finding.entity_type
                and flag.get("entity_id") == finding.entity_id
                and flag.get("severity") == finding.severity
                and str(flag.get("reason", "")).startswith(f"[blue:{finding.id}] ")
                for flag in snapshot.datasets.get("flags", [])
            ):
                session.suppressed.add(finding.id)
    rows = snapshot.datasets["crs"]
    return {status: sum(row["status"] == status for row in rows) for status in ("verified", "mismatch", "review", "unknown")}


@blue_tool("raise_flag", "Raise a service-defined, corroborated snapshot finding by finding_id. No arbitrary entity, severity or reason.")
async def raise_flag(finding_id: str) -> dict[str, Any]:
    session = current()
    finding = _find(finding_id)
    if finding.id in session.suppressed:
        return {"ok": True, "already_flagged": True}
    result = await _write(
        "flag",
        finding.id,
        lambda invocation: ctx.ledger().raise_flag(
            finding.entity_type,
            finding.entity_id,
            finding.severity,
            finding.reason,
            tool_use_id=invocation,
        ),
    )
    if result["ok"]:
        session.suppressed.add(finding.id)
    return result


def freeze_authorized(findings: list[Finding]) -> bool:
    evidence = [e for finding in findings for e in finding.evidence]
    return len({e.family for e in evidence}) >= 2 and any(e.substantive and e.family in {"integrity", "identity"} for e in evidence)


@blue_tool("freeze_vendor", "Freeze a current vendor using finding_ids from two independent families, including substantive integrity or identity evidence.")
async def freeze_vendor(vendor_id: str, finding_ids: list[str]) -> dict[str, Any]:
    session = current()
    if not valid_id(vendor_id) or not isinstance(finding_ids, list) or not 2 <= len(finding_ids) <= 20:
        raise ValueError("Unsupported freeze request.")
    findings = [_find(finding_id) for finding_id in set(finding_ids)]
    if any(f.vendor_id != vendor_id for f in findings) or not freeze_authorized(findings):
        raise ValueError("Independent substantive evidence is required.")
    if any(e.kind == "freeze" and e.key == vendor_id for e in session.effects):
        existing = next(e for e in session.effects if e.kind == "freeze" and e.key == vendor_id)
        return {"ok": existing.state == "confirmed", "state": existing.state, "replayed": True}
    if sum(e.kind == "freeze" for e in session.effects) >= 4:
        session.gaps.append("Additional freeze candidates need a human")
        return {"ok": False, "error": "Freeze limit reached."}
    snapshot = session.snapshot
    assert snapshot is not None
    prior = next((v for v in snapshot.datasets.get("vendors", []) if v["id"] == vendor_id), None)
    if prior is None:
        raise ValueError("Vendor not in snapshot.")
    async with asyncio.timeout(WRITE_TIMEOUT):
        fresh = await ctx.ledger().get_vendor(vendor_id)
    if (
        not isinstance(fresh, dict)
        or fresh.get("id") != vendor_id
        or fresh.get("episode_id", session.episode_id) != session.episode_id
        or any(fresh.get(key) != prior.get(key) for key in ("bank_account", "bank_routing", "created_day"))
        or fresh.get("status") not in {"active", "frozen"}
    ):
        raise ValueError("Fresh vendor evidence differs; do not act on stale evidence.")
    if fresh["status"] == "frozen":
        return {"ok": True, "already_frozen": True}
    reason = "Independent validated controls: " + ", ".join(sorted({f.code for f in findings})) + ". Human review required to release."
    return await _write("freeze", vendor_id, lambda invocation: ctx.ledger().freeze_vendor(vendor_id, reason, tool_use_id=invocation))


def report_markdown() -> str:
    session = current()
    snapshot = session.snapshot
    assert snapshot is not None
    outcome = session.outcome()
    gaps = sorted({c.dataset for c in snapshot.coverage if c.status != "complete"})
    failures = sum(e.state == "failed" for e in session.effects)
    unknown = sum(e.state in {"unknown", "attempted"} for e in session.effects) + len(session.unresolved)
    codes = sorted({f.code for f in snapshot.findings})[:6]
    actioned = session.suppressed | {e.key for e in session.effects if e.kind == "flag"}
    remaining = len({f.id for f in snapshot.findings} - actioned)
    text = (
        f"# Day {session.day} controller report\n\n"
        f"## Reviewed\n{len(snapshot.datasets.get('invoices', []))} invoices, "
        f"{len(snapshot.datasets.get('vendors', []))} vendors, {len(snapshot.datasets.get('payments', []))} payments today; "
        "employees, POs, changes, flags and allowlisted Green activity. Public APIs are unpaginated; upstream completeness is unproven. "
        f"CRS unknown/step-up: {sum(r['status'] in {'unknown', 'review'} for r in snapshot.datasets.get('crs', []))}.\n\n"
        f"## Flagged\n{outcome.flags_raised} confirmed new flags; {len(session.suppressed)} finding receipts/existing flags recorded; "
        f"{outcome.vendors_frozen} confirmed freezes. Controls: {', '.join(codes) or 'none'}.\n\n"
        f"## Needs a human tomorrow\nCoverage gaps: {', '.join(gaps) or 'none observed locally'}. "
        f"Writes failed: {failures}; unknown: {unknown}; findings not actioned: {remaining}. "
        "Never blindly retry unknown writes. Independently verify destination and ownership exceptions. "
        f"{'; '.join(session.gaps[:3])}. Report delivery is confirmed separately."
    )
    # All interpolations are bounded service-derived facts, not user/model prose.
    assert len(text.split()) < 200
    return text


@blue_tool("post_report", "Post the service-generated report under 200 words with Reviewed, Flagged, Needs a human tomorrow and confirmed receipts.")
async def post_report() -> dict[str, Any]:
    markdown = report_markdown()
    return await _write("report", str(current().day), lambda invocation: ctx.ledger().post_report(current().day, markdown, tool_use_id=invocation))
