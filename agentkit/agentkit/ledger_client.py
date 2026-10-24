"""Typed HTTP client for battlefield's Ledger API.

This is the ONLY way an agent touches the books. Every call sets X-Agent / X-Episode / X-Day and,
for writes, X-Tool-Use-Id (the idempotency key). A blocked gated call raises `GateBlocked` with
the verdict reason so the agent (or its prompt) can react.

X-Tool-Use-Id, in order of precedence: the `tool_use_id=` you pass; else, inside a tool call, the
current invocation's key (the Droid tool_use_id for the call's first write, `<id>:<n>` for the n-th;
see agentkit.invocation); else a fresh UUID4.

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
from .invocation import current_invocation
from .models import AttackCreate


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


class LedgerClient:
    def __init__(self, settings: AgentSettings, *, episode_id: str, day: int):
        self.s = settings
        self.episode_id = episode_id
        self.day = day
        self._client: httpx.AsyncClient | None = None

    # ---------- lifecycle ----------
    async def __aenter__(self) -> LedgerClient:
        self._client = httpx.AsyncClient(
            base_url=f"{self.s.battlefield_url.rstrip('/')}/api",
            timeout=httpx.Timeout(self.s.http_timeout_sec, read=max(self.s.http_timeout_sec, 120)),
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
