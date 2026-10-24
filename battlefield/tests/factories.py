"""Row factories for DB-tier tests. Tests may write the DB directly; agents never do."""

from __future__ import annotations

import uuid
from typing import Any

from app import db

AGENT_TOKEN = "test-agent-token"
OPERATOR_TOKEN = "test-operator-token"


def auth(
    agent: str | None = None, *, episode: str | None = "ep_test", day: int | None = 0, tool_use_id: str | None = None, token: str | None = None
) -> dict[str, str]:
    """Headers for an agent (X-Agent + AGENT_TOKEN) or, with no agent, the operator (OPERATOR_TOKEN)."""
    if token is None:
        token = AGENT_TOKEN if agent is not None else OPERATOR_TOKEN
    h = {"Authorization": f"Bearer {token}"}
    if agent is not None:
        h["X-Agent"] = agent
        if episode is not None:
            h["X-Episode"] = episode
        if day is not None:
            h["X-Day"] = str(day)
    if tool_use_id is not None:
        h["X-Tool-Use-Id"] = tool_use_id
    return h


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def insert(table: str, **cols: Any) -> str:
    """INSERT one row; returns its id (generated from the table name if not given)."""
    if table not in {"vendors", "vendor_changes", "invoices", "expenses", "employees", "payments", "attacks", "verdicts", "flags"}:
        raise ValueError(table)
    cols.setdefault("id", uid(table[:3]))
    names = list(cols)
    placeholders = ",".join(f"${i + 1}" for i in range(len(names)))
    await db.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})", *cols.values())
    return cols["id"]


async def vendor(ep: str, *, origin: str = "sim", bank_account: str = "ACCT-OLD", status: str = "active") -> str:
    return await insert(
        "vendors", episode_id=ep, name=uid("Vendor"), bank_account=bank_account, bank_routing="021000021", created_day=-30, origin=origin, status=status
    )


async def attack(ep: str, *, day: int = 1, scheme_id: str = "bank_swap", target_amount: float = 10_000.0) -> str:
    return await insert("attacks", episode_id=ep, scheme_id=scheme_id, display_name=scheme_id, story="test", day_launched=day, target_amount=target_amount)


async def invoice(
    ep: str, vendor_id: str, *, amount: float = 1000.0, origin: str = "sim", status: str = "pending", attack_id: str | None = None, day: int = 0
) -> str:
    return await insert(
        "invoices",
        episode_id=ep,
        vendor_id=vendor_id,
        amount=amount,
        invoice_number=uid("INV"),
        received_day=day,
        due_day=day + 30,
        status=status,
        status_day=day,
        origin=origin,
        attack_id=attack_id,
    )


async def employee(ep: str) -> str:
    return await insert("employees", episode_id=ep, name="E", role="clerk", salary=50_000, bank_account="EMP-1", start_day=-100)


async def expense(ep: str, employee_id: str, *, amount: float = 200.0, origin: str = "sim", status: str = "pending", attack_id: str | None = None) -> str:
    return await insert(
        "expenses", episode_id=ep, employee_id=employee_id, amount=amount, category="travel", submitted_day=0, status=status, origin=origin, attack_id=attack_id
    )


async def change(
    ep: str,
    vendor_id: str,
    *,
    origin: str = "red",
    day: int = 1,
    status: str = "pending",
    resolved_day: int | None = None,
    new_value: str = "ACCT-RED",
    field: str = "bank_account",
) -> str:
    return await insert(
        "vendor_changes",
        episode_id=ep,
        vendor_id=vendor_id,
        field=field,
        old_value="ACCT-OLD",
        new_value=new_value,
        requested_day=day,
        status=status,
        resolved_day=resolved_day,
        origin=origin,
    )


async def payment(ep: str, invoice_id: str, *, amount: float, to_account: str, day: int, origin_of_source: str = "sim") -> str:
    return await insert(
        "payments", episode_id=ep, invoice_id=invoice_id, amount=amount, to_account=to_account, paid_day=day, paid_by="green", origin_of_source=origin_of_source
    )


async def verdict(ep: str, entity_type: str, entity_id: str, *, verdict: str = "block", day: int = 1) -> str:
    return await insert(
        "verdicts",
        episode_id=ep,
        idempotency_key=uid("tu"),
        day=day,
        agent="green",
        action=f"{entity_type}s.approve",
        entity_type=entity_type,
        entity_id=entity_id,
        verdict=verdict,
        reason="test",
        enforced=True,
    )


async def flag(ep: str, entity_type: str, entity_id: str, *, day: int = 1) -> str:
    return await insert("flags", episode_id=ep, day=day, entity_type=entity_type, entity_id=entity_id, severity="high", reason="test", raised_by="blue")
