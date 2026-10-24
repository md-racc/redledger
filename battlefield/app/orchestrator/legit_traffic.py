"""Scripted legitimate business for one simulated day. Owner: Dev Ad (plumbing) / Dev M (realism).

Deterministic from (seed, day). Produces origin='sim' rows that green must process correctly:
these are the false-positive bait. Dev M: tune volumes and shapes here so green has real work
and blue has real risk of over-blocking. Keep it deterministic.
"""

from __future__ import annotations

import random
from typing import Any

from .. import db

ACCOUNTS = ["5100 Office Supplies", "5200 Logistics", "5300 IT Services", "5400 Facilities", "5500 Professional Services"]


async def inject(episode_id: str, seed: int, day: int) -> dict[str, int]:
    rng = random.Random(seed * 1009 + day)
    vendors = [dict(r) for r in await db.fetch("SELECT * FROM vendors WHERE episode_id=$1 AND origin='sim' AND status='active'", episode_id)]
    employees = [dict(r) for r in await db.fetch("SELECT * FROM employees WHERE episode_id=$1 AND origin='sim' AND status='active'", episode_id)]
    counts = {"invoices": 0, "purchase_orders": 0, "expenses": 0, "bank_lines": 0}
    if not vendors:
        return counts

    # 2-4 new POs
    for _ in range(rng.randint(2, 4)):
        v = rng.choice(vendors)
        amount = round(rng.uniform(400, 12000), 2)
        await db.execute(
            "INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, description, created_day, origin) VALUES ($1,$2,$3,$4,$5,$6,'sim')",
            db.new_id("po"),
            episode_id,
            v["id"],
            amount,
            _po_desc(rng, v),
            day,
        )
        counts["purchase_orders"] += 1

    # 3-6 invoices, mostly against open POs, a couple without (legit no-PO vendors exist)
    open_pos = [
        dict(r)
        for r in await db.fetch("SELECT * FROM purchase_orders WHERE episode_id=$1 AND status='open' AND origin='sim' AND created_day < $2", episode_id, day)
    ]
    for _ in range(rng.randint(3, 6)):
        if open_pos and rng.random() < 0.8:
            po = open_pos.pop(rng.randrange(len(open_pos)))
            vid, po_id = po["vendor_id"], po["id"]
            amount = round(float(po["amount"]) * rng.uniform(0.97, 1.03), 2)  # small legit variance
        else:
            v = rng.choice(vendors)
            vid, po_id = v["id"], None
            amount = round(rng.uniform(150, 2500), 2)
        await db.execute(
            "INSERT INTO invoices (id, episode_id, vendor_id, po_id, amount, invoice_number, line_items, received_day, due_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'sim')",
            db.new_id("inv"),
            episode_id,
            vid,
            po_id,
            amount,
            f"INV-{rng.randint(10000, 99999)}",
            [{"desc": "services", "amount": amount}],
            day,
            day + 30,
        )
        counts["invoices"] += 1

    # 1-3 expenses
    for _ in range(rng.randint(1, 3)):
        e = rng.choice(employees) if employees else None
        if not e:
            break
        amount = round(rng.uniform(20, 600), 2)
        await db.execute(
            "INSERT INTO expenses (id, episode_id, employee_id, amount, category, memo, submitted_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,'sim')",
            db.new_id("exp"),
            episode_id,
            e["id"],
            amount,
            rng.choice(["travel", "meals", "software", "supplies"]),
            "",
            day,
        )
        counts["expenses"] += 1

    # a few inbound bank lines (customer receipts) so the feed isn't only outflows
    for _ in range(rng.randint(1, 3)):
        await db.execute(
            "INSERT INTO bank_transactions (id, episode_id, day, amount, counterparty, memo) VALUES ($1,$2,$3,$4,$5,$6)",
            db.new_id("bnk"),
            episode_id,
            day,
            round(rng.uniform(2000, 40000), 2),
            f"Customer {rng.randint(100, 999)}",
            "Receipt",
        )
        counts["bank_lines"] += 1
    return counts


def _po_desc(rng: random.Random, v: dict[str, Any]) -> str:
    cat = v.get("category") or "services"
    return rng.choice([f"{cat} — monthly", f"{cat} — project work", f"{cat} — replenishment", f"{cat} — Q4 order"])
