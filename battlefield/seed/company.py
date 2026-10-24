"""Seed Coastal Supply Co. for a new episode. Owner: Dev Ad (plumbing) / Dev M (realism).

Deterministic from `seed`. Produces 90 days of clean history: vendors, employees, POs, paid
invoices, payments, bank feed, GL. Everything origin='sim'. Dev M: make this look like a real
QuickBooks export — vendor categories, recurring monthly vendors, realistic amounts.
"""

from __future__ import annotations

import random

from faker import Faker

from app import db

HISTORY_DAYS = 90
N_VENDORS = 60
N_EMPLOYEES = 40
CATEGORIES = ["office", "logistics", "it", "facilities", "professional", "marketing", "raw_materials"]
GL_EXPENSE = {
    "office": "5100 Office Supplies",
    "logistics": "5200 Logistics",
    "it": "5300 IT Services",
    "facilities": "5400 Facilities",
    "professional": "5500 Professional Services",
    "marketing": "5600 Marketing",
    "raw_materials": "5000 COGS",
}


def _acct(rng: random.Random) -> str:
    return str(rng.randint(10**9, 10**10 - 1))


def _routing(rng: random.Random) -> str:
    return str(rng.randint(10**8, 10**9 - 1))


async def seed_episode(episode_id: str, seed: int) -> None:
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)

    vendors: list[dict] = []
    for _i in range(N_VENDORS):
        cat = rng.choice(CATEGORIES)
        v = {
            "id": db.new_id("ven"),
            "name": fake.company(),
            "ein": f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}",
            "bank_account": _acct(rng),
            "bank_routing": _routing(rng),
            "address": fake.address().replace("\n", ", "),
            "category": cat,
            "created_day": -rng.randint(HISTORY_DAYS, 900),
            "recurring": rng.random() < 0.3,
            "typical": round(rng.uniform(300, 9000), 2),
        }
        vendors.append(v)
        await db.execute(
            "INSERT INTO vendors (id, episode_id, name, ein, bank_account, bank_routing, address, category, created_day, origin, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'sim','seed')",
            v["id"],
            episode_id,
            v["name"],
            v["ein"],
            v["bank_account"],
            v["bank_routing"],
            v["address"],
            v["category"],
            v["created_day"],
        )

    for _i in range(N_EMPLOYEES):
        await db.execute(
            "INSERT INTO employees (id, episode_id, name, role, department, salary, bank_account, start_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'sim')",
            db.new_id("emp"),
            episode_id,
            fake.name(),
            rng.choice(["Ops", "Sales", "Engineer", "Warehouse", "Finance", "Support"]),
            rng.choice(["operations", "sales", "engineering", "warehouse", "finance"]),
            round(rng.uniform(48000, 140000), 2),
            _acct(rng),
            -rng.randint(30, 2000),
        )

    # 90 days of paid history
    for day in range(-HISTORY_DAYS, 0):
        for v in vendors:
            monthly = v["recurring"] and day % 30 == -5
            adhoc = (not v["recurring"]) and rng.random() < 0.04
            if not (monthly or adhoc):
                continue
            amount = round(v["typical"] * rng.uniform(0.9, 1.1), 2)
            po_id = db.new_id("po")
            await db.execute(
                "INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, description, created_day, status, origin) VALUES ($1,$2,$3,$4,$5,$6,'fulfilled','sim')",
                po_id,
                episode_id,
                v["id"],
                amount,
                f"{v['category']} — {'monthly' if monthly else 'order'}",
                day - rng.randint(3, 10),
            )
            inv_id = db.new_id("inv")
            inv_num = f"INV-{rng.randint(10000, 99999)}"
            await db.execute(
                "INSERT INTO invoices (id, episode_id, vendor_id, po_id, amount, invoice_number, line_items, received_day, due_day, status, status_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'paid',$10,'sim')",
                inv_id,
                episode_id,
                v["id"],
                po_id,
                amount,
                inv_num,
                [{"desc": v["category"], "amount": amount}],
                day,
                day + 30,
                day + rng.randint(2, 12),
            )
            pay_id = db.new_id("pay")
            paid_day = day + rng.randint(2, 12)
            await db.execute(
                "INSERT INTO payments (id, episode_id, invoice_id, amount, to_account, paid_day, paid_by, origin_of_source) VALUES ($1,$2,$3,$4,$5,$6,'seed','sim')",
                pay_id,
                episode_id,
                inv_id,
                amount,
                v["bank_account"],
                paid_day,
            )
            await db.execute(
                "INSERT INTO bank_transactions (id, episode_id, day, amount, counterparty, memo, matched_payment_id) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                db.new_id("bnk"),
                episode_id,
                paid_day,
                -amount,
                v["name"],
                f"ACH {inv_num}",
                pay_id,
            )
            await db.execute(
                "INSERT INTO gl_entries (id, episode_id, day, account, debit, credit, memo, posted_by, ref_type, ref_id) VALUES ($1,$2,$3,$4,$5,0,$6,'seed','invoice',$7)",
                db.new_id("gl"),
                episode_id,
                day,
                GL_EXPENSE[v["category"]],
                amount,
                inv_num,
                inv_id,
            )
            await db.execute(
                "INSERT INTO gl_entries (id, episode_id, day, account, debit, credit, memo, posted_by, ref_type, ref_id) VALUES ($1,$2,$3,'2000 Accounts Payable',0,$4,$5,'seed','invoice',$6)",
                db.new_id("gl"),
                episode_id,
                day,
                amount,
                inv_num,
                inv_id,
            )
        # receipts
        if day % 3 == 0:
            await db.execute(
                "INSERT INTO bank_transactions (id, episode_id, day, amount, counterparty, memo) VALUES ($1,$2,$3,$4,$5,'Receipt')",
                db.new_id("bnk"),
                episode_id,
                day,
                round(rng.uniform(5000, 60000), 2),
                f"Customer {rng.randint(100, 999)}",
            )

    # a few open POs heading into day 0 so green has matches available immediately
    for v in rng.sample(vendors, 6):
        await db.execute(
            "INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, description, created_day, status, origin) VALUES ($1,$2,$3,$4,$5,$6,'open','sim')",
            db.new_id("po"),
            episode_id,
            v["id"],
            round(v["typical"] * rng.uniform(0.9, 1.1), 2),
            f"{v['category']} — open",
            -rng.randint(1, 6),
        )
