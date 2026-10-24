"""Typed HTTP client for battlefield's Ledger API.

This is the ONLY way an agent touches the books. Every call sets X-Agent / X-Episode / X-Day and,
for writes, X-Tool-Use-Id (the idempotency key). A blocked gated call raises `GateBlocked` with
the verdict reason so the agent (or its prompt) can react.

X-Tool-Use-Id, in order of precedence: the `tool_use_id=` you pass; else, inside a tool call, the
current invocation's key (the Droid tool_use_id for the call's first write, `<id>:<n>` for the n-th;
see agentkit.invocation); else a fresh UUID4. An explicit key that the current invocation already
sent raises agentkit.invocation.IdempotencyKeyReused before the request goes out.

Strict identity (a strict agent's live turn, design B-2): every write needs a current invocation whose id
the Droid SDK reported, and an explicit key must belong to it (`<id>` or `<id>:<n>`); otherwise
UnverifiedInvocation is raised before anything is sent. UUID4 keys remain for DRY_RUN and best_effort.

Usage inside a turn:

    async with LedgerClient(settings, episode_id=ep, day=d) as ledger:
        invoices = await ledger.list_invoices(status="pending")
        await ledger.pay_invoice(inv["id"], tool_use_id=tool_use_id)
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from .config import AgentSettings
from .invocation import VERIFIED_SOURCES, ToolUse, UnverifiedInvocation, current_invocation, strict_identity
from .models import AttackCreate, GatedAction, Preparation, PreparationCreate
from .models import PreparationRejected as PreparationRejectedBody


class LedgerError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"ledger {status}: {body}")
        self.status = status
        self.body = body


class GateBlocked(LedgerError):
    """A gated green action was blocked (or escalated and then blocked)."""

    def __init__(self, body: dict[str, Any]):
        super().__init__(403, body)
        self.reason: str = body.get("reason", "")
        self.verdict_id: str | None = body.get("verdict_id")
        self.cause: str | None = body.get("cause")  # control | gate_unavailable
        self.escalation_id: str | None = body.get("escalation_id")
        self.preparation_id: str | None = body.get("preparation_id")


class PreparationRejected(LedgerError):
    """409: the gated route refused to consume the call's preparation (expired, stale, consumed, pending)."""

    def __init__(self, body: dict[str, Any]):
        super().__init__(409, body)
        parsed = PreparationRejectedBody.model_validate(body)
        self.error: str = parsed.error
        self.preparation_id: str = parsed.preparation_id
        self.detail: str = parsed.detail
        self.consumed_status: int | None = parsed.consumed_status


class LedgerClient:
    def __init__(self, settings: AgentSettings, *, episode_id: str, day: int):
        self.s = settings
        self.episode_id = episode_id
        self.day = day
        self._client: httpx.AsyncClient | None = None

    @staticmethod
    def read_timeout_sec(s: AgentSettings) -> float:
        """Read timeout for Ledger API calls. A gated green write may be held by battlefield for a human
        for up to ESCALATION_TIMEOUT_SEC after blue's gate call (GATE_TIMEOUT_SEC), so the read must
        outlast both, plus slack for the database work around them; otherwise the client gives up while
        battlefield still holds the call and may still execute it."""
        return max(s.http_timeout_sec, s.escalation_timeout_sec + s.gate_timeout_sec + 15)

    # ---------- lifecycle ----------
    async def __aenter__(self) -> LedgerClient:
        self._client = httpx.AsyncClient(
            base_url=f"{self.s.battlefield_url.rstrip('/')}/api",
            timeout=httpx.Timeout(self.s.http_timeout_sec, read=self.read_timeout_sec(self.s)),
            headers={
                "Authorization": f"Bearer {self.s.internal_token}",
                "X-Agent": self.s.agent_name,
                "X-Episode": self.episode_id,
                "X-Day": str(self.day),
            },
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def c(self) -> httpx.AsyncClient:
        assert self._client is not None, "use `async with LedgerClient(...)`"
        return self._client

    # ---------- plumbing ----------
    @staticmethod
    def new_tool_use_id() -> str:
        return uuid.uuid4().hex

    async def _get(self, path: str, **params: Any) -> Any:
        r = await self.c.get(path, params={k: v for k, v in params.items() if v is not None})
        return self._handle(r)

    async def _write(self, method: str, path: str, body: dict[str, Any] | list[Any] | None, tool_use_id: str | None) -> Any:
        inv = current_invocation()
        if strict_identity() and not self.s.dry_run:
            if inv is None or not inv.verified:
                raise UnverifiedInvocation(f"{method} {path}: no verified tool_use_id for this write (strict identity)")
            if tool_use_id and tool_use_id != inv.tool_use_id and not tool_use_id.startswith(f"{inv.tool_use_id}:"):
                raise UnverifiedInvocation(f"{method} {path}: X-Tool-Use-Id {tool_use_id!r} is not this call's id (strict identity)")
        if tool_use_id:
            if inv is not None:
                inv.reserve(tool_use_id)
            key = tool_use_id
        else:
            key = inv.next_key() if inv is not None else self.new_tool_use_id()
        headers = {"X-Tool-Use-Id": key}
        r = await self.c.request(method, path, json=body, headers=headers)
        return self._handle(r)

    @staticmethod
    def _handle(r: httpx.Response) -> Any:
        if r.status_code == 409:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text}
            if isinstance(body, dict) and str(body.get("error", "")).startswith("preparation_") and body.get("preparation_id"):
                raise PreparationRejected(body)
            raise LedgerError(409, body)
        if r.status_code == 403:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"reason": r.text}
            if isinstance(body, dict) and body.get("verdict") == "block":
                raise GateBlocked(body)
            raise LedgerError(403, body)
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise LedgerError(r.status_code, body)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ---------- reads (all agents) ----------
    async def list_vendors(self, status: str | None = None) -> list[dict]:
        return await self._get("/vendors", status=status)

    async def get_vendor(self, vendor_id: str) -> dict:
        return await self._get(f"/vendors/{vendor_id}")

    # ---------- gate preparations (green; contracts/ledger-api.yaml /preparations) ----------
    async def prepare(self, use: ToolUse, action: GatedAction, entity_id: str | None, args: dict[str, Any] | None = None) -> Preparation:
        """Gate a tool call before it runs (from the permission handler), keyed by the call's SDK
        tool_use_id. Refuses a use whose id the SDK did not report. A block returns 200 too: read
        `effective`. Sent outside any invocation, so it never consumes one of the call's write keys."""
        if use.source not in VERIFIED_SOURCES:
            raise UnverifiedInvocation(f"prepare {action}: tool_use_id {use.tool_use_id!r} has source {use.source!r}, not an SDK-reported id")
        body = PreparationCreate(action=action, entity_id=entity_id, args=args or {}).model_dump()
        r = await self.c.post("/preparations", json=body, headers={"X-Tool-Use-Id": use.tool_use_id})
        return Preparation.model_validate(self._handle(r))

    async def get_preparation(self, key: str) -> Preparation | None:
        """The preparation stored under `key` in this episode, or None (e.g. to reconcile without retrying)."""
        r = await self.c.get(f"/preparations/{key}")
        if r.status_code == 404:
            return None
        return Preparation.model_validate(self._handle(r))

    async def list_vendor_changes(self, status: str | None = None) -> list[dict]:
        return await self._get("/vendor_changes", status=status)

    async def list_employees(self) -> list[dict]:
        return await self._get("/employees")

    async def list_purchase_orders(self, status: str | None = None, vendor_id: str | None = None) -> list[dict]:
        return await self._get("/purchase_orders", status=status, vendor_id=vendor_id)

    async def list_invoices(self, status: str | None = None, vendor_id: str | None = None, day: int | None = None) -> list[dict]:
        return await self._get("/invoices", status=status, vendor_id=vendor_id, day=day)

    async def get_invoice(self, invoice_id: str) -> dict:
        return await self._get(f"/invoices/{invoice_id}")

    async def list_payments(self, day: int | None = None) -> list[dict]:
        return await self._get("/payments", day=day)

    async def list_expenses(self, status: str | None = None) -> list[dict]:
        return await self._get("/expenses", status=status)

    async def list_bank_transactions(self, from_day: int | None = None, to_day: int | None = None) -> list[dict]:
        return await self._get("/bank/transactions", from_day=from_day, to_day=to_day)

    async def list_gl_entries(self, from_day: int | None = None, to_day: int | None = None, account: str | None = None) -> list[dict]:
        return await self._get("/gl/entries", from_day=from_day, to_day=to_day, account=account)

    async def list_flags(self) -> list[dict]:  # green, blue
        return await self._get("/flags")

    async def list_audit_log(self, agent: str | None = None, day: int | None = None) -> list[dict]:  # blue
        return await self._get("/audit_log", agent=agent, day=day)

    # ---------- extension points (all agents) ----------
    async def get_state(self, key: str) -> dict:
        """Per-agent JSON memory across turns (agent_state table). Returns {} if unset."""
        return await self._get(f"/state/{key}")

    async def put_state(self, key: str, value: dict[str, Any]) -> dict:
        return await self._write("PUT", f"/state/{key}", value, None)

    async def post_input(self, target: str, payload: dict[str, Any]) -> dict:
        """Leave a message for another agent's next turn (lands in its options.inputs)."""
        return await self._write("POST", "/inputs", {"episode_id": self.episode_id, "target": target, "payload": payload}, None)

    # ---------- playbook (lineage episodes only; contracts/agent-service.md "Lineages") ----------
    async def get_playbook(self) -> dict | None:
        """Your latest playbook version in this episode's lineage, or None outside a lineage (404)."""
        try:
            return await self._get("/playbook")
        except LedgerError as e:
            if e.status == 404:
                return None
            raise

    async def put_playbook(self, content: dict[str, Any], rationale: str, base_version: int, *, tool_use_id: str | None = None) -> dict:
        """Write the next version (active turn only). 409 on a stale base_version: re-read and retry."""
        return await self._write("PUT", "/playbook", {"content": content, "rationale": rationale, "base_version": base_version}, tool_use_id)

    async def playbook_history(self, limit: int = 20) -> list[dict]:
        """Your own versions, newest first; [] outside a lineage."""
        try:
            return await self._get("/playbook/history", limit=limit)
        except LedgerError as e:
            if e.status == 404:
                return []
            raise

    # ---------- red writes ----------
    async def create_vendor(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/vendors", body, tool_use_id)

    async def request_vendor_change(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/vendor_changes", body, tool_use_id)

    async def submit_invoice(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/invoices", body, tool_use_id)

    async def submit_expense(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/expenses", body, tool_use_id)

    async def create_employee(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/employees", body, tool_use_id)

    async def declare_attack(self, attack: AttackCreate, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/attacks", attack.model_dump(), tool_use_id)

    async def annotate_attack(self, attack_id: str, notes: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("PATCH", f"/attacks/{attack_id}", {"notes": notes}, tool_use_id)

    # ---------- green writes (gated) ----------
    async def match_invoice(self, invoice_id: str, po_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/invoices/{invoice_id}/match", {"po_id": po_id}, tool_use_id)

    async def approve_invoice(self, invoice_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/invoices/{invoice_id}/approve", None, tool_use_id)

    async def reject_invoice(self, invoice_id: str, reason: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/invoices/{invoice_id}/reject", {"reason": reason}, tool_use_id)

    async def pay_invoice(self, invoice_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/invoices/{invoice_id}/pay", None, tool_use_id)

    async def approve_vendor_change(self, change_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/vendor_changes/{change_id}/approve", None, tool_use_id)

    async def reject_vendor_change(self, change_id: str, reason: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/vendor_changes/{change_id}/reject", {"reason": reason}, tool_use_id)

    async def approve_expense(self, expense_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/expenses/{expense_id}/approve", None, tool_use_id)

    async def pay_expense(self, expense_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/expenses/{expense_id}/pay", None, tool_use_id)

    async def post_gl_entry(self, body: dict[str, Any], *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/gl/entries", body, tool_use_id)

    # ---------- blue writes ----------
    async def raise_flag(self, entity_type: str, entity_id: str, severity: str, reason: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/flags", {"entity_type": entity_type, "entity_id": entity_id, "severity": severity, "reason": reason}, tool_use_id)

    async def freeze_vendor(self, vendor_id: str, reason: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/vendors/{vendor_id}/freeze", {"reason": reason}, tool_use_id)

    async def unfreeze_vendor(self, vendor_id: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", f"/vendors/{vendor_id}/unfreeze", None, tool_use_id)

    async def post_report(self, day: int, markdown: str, *, tool_use_id: str | None = None) -> dict:
        return await self._write("POST", "/reports", {"day": day, "markdown": markdown}, tool_use_id)
