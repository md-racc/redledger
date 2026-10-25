"""Scripted legitimate business for one simulated day. Owner: Dev Ad (plumbing) / Dev M (realism).

Deterministic from (seed, day) and the ledger state. Produces origin='sim' rows that green must
process correctly: these are the false-positive bait. Dev M: tune volumes and shapes here so green
has real work and blue has real risk of over-blocking. Keep it deterministic: every random draw
comes from an RNG seeded from (seed, day); every candidate list is ORDER BY'd on stable columns
(row ids are random, so they never decide a pick).

Per day:
  - 2-4 POs and 3-6 invoices (mostly against open, not-yet-billed POs; some without a PO),
    1-3 expenses, 1-3 customer receipts.
  - Legit bank-detail changes: one in every BANK_CHANGE_WINDOW days, on a seeded day inside each
    window. An established vendor (at least ESTABLISHED_AGE days old, no change requested in that
    long and none pending) asks to move its remittance account, old_value = its current account.
    About BANK_CHANGE_OPEN_SHARE of them come from a vendor with open invoices. Bait for "bank
    change requested" / "bank change with open invoices" and, once approved, for "recent bank
    change" on that vendor's next large payment.
  - Legit new vendors: one in every NEW_VENDOR_WINDOW days. A new vendor is onboarded
    (created_day=day) with a real PO the same day; its first invoice, against that PO and above
    $1,000, arrives 1..FIRST_INVOICE_MAX_DELAY days later. Bait for "vendor age < 7d" on a vendor
    that, unlike a ghost vendor, has a PO behind its invoice.

Writes go straight to the DB (battlefield-internal, like the seed): no audit_log rows, no events.
The day's counts go out in `day.started.legit_injected`.
"""

from __future__ import annotations

import random
from typing import Any

from faker import Faker

from .. import db

ACCOUNTS = ["5100 Office Supplies", "5200 Logistics", "5300 IT Services", "5400 Facilities", "5500 Professional Services"]
CATEGORIES = ["office", "logistics", "it", "facilities", "professional", "marketing", "raw_materials"]

ESTABLISHED_AGE = 30  # days: bank-change candidates are at least this old, with no change this recent
GENERIC_MIN_AGE = 7  # days: a newly onboarded vendor joins the generic PO/invoice traffic after this
BANK_CHANGE_WINDOW = 3  # one legit bank-account change per window of this many days
BANK_CHANGE_OPEN_SHARE = 0.6  # share of those changes requested while the vendor has open invoices
NEW_VENDOR_WINDOW = 4  # one legit new vendor per window of this many days
FIRST_INVOICE_MAX_DELAY = 2  # a new vendor's first invoice arrives 1..this many days after onboarding
ONBOARDED_BY = "procurement"  # vendors.created_by for legit vendors onboarded mid-episode (the seed uses 'seed')

OPEN_INVOICE_STATUSES = ["pending", "matched", "approved"]

BANK_CHANGE_REASONS = [
    "Our bank was acquired by {bank}; the old account closes at month end. Please send all future ACH payments to the new account.",
    "We have consolidated treasury with our parent company. Please update our remittance details for future payments.",
    "We moved our operating account to {bank}. Updated remittance instructions and a voided cheque are attached.",
    "Our AR team has a new collection account at {bank} as of this month. Please update the account on file.",
    "Account change following our bank's merger with {bank}. Routing is unchanged; please update the account number.",
    "We have migrated to a new banking partner effective this month; please update remittance details for all open and future invoices.",
]

# Free text on legit rows. Without it legit memos were always "" and line items a bare category, so
# a non-empty memo or a descriptive line item alone told red's rows apart (invariant 4). Drawn from
# a separate RNG stream (_rng(..., "text")), so the amounts, vendors and days of the day's traffic
# are unchanged for a given seed.
EXPENSE_MEMOS = {
    "travel": ["Client site visit — mileage and lodging", "Airfare to regional office", "Taxi to client meeting", "travel reimbursement"],
    "meals": ["Team dinner, {n} attendees", "Client lunch", "Working lunch during inventory count", "meals reimbursement"],
    "software": ["Annual license renewal", "Monthly SaaS subscription", "Design tool seat", "software reimbursement"],
    "supplies": ["Field kit and replacement parts", "Printer toner and paper", "Packing materials", "supplies reimbursement"],
}


def _line_desc(text: random.Random, category: str | None, po_desc: str | None = None) -> str:
    cat = category or "services"
    return text.choice([po_desc or cat, cat, "services", f"{cat} — monthly", f"{cat} — {text.choice(['order', 'service call', 'replenishment'])}"])


BANKS = ["First Harbor Bank", "Pacific Trust", "Meridian National", "Summit Federal", "Northgate Bank", "Bayview Credit Union"]


def _rng(seed: int, day: int, purpose: str) -> random.Random:
    """One stream per (seed, day, purpose). str seeds are hashed with sha512: stable across processes."""
    return random.Random(f"legit:{seed}:{day}:{purpose}")


def _scheduled(seed: int, day: int, window: int, purpose: str) -> bool:
    """True on exactly one seeded day in each window of `window` days ([0, w), [w, 2w), ...)."""
    if day < 0:
        return False
    start = day - day % window
    return day == start + random.Random(f"legit:{seed}:{purpose}:window:{start}").randrange(window)


def bank_change_scheduled(seed: int, day: int) -> bool:
    return _scheduled(seed, day, BANK_CHANGE_WINDOW, "bank_change")


def new_vendor_scheduled(seed: int, day: int) -> bool:
    return _scheduled(seed, day, NEW_VENDOR_WINDOW, "new_vendor")


def first_invoice_delay(seed: int, onboard_day: int) -> int:
    """Days between a new vendor's onboarding and its first invoice (1..FIRST_INVOICE_MAX_DELAY)."""
    return random.Random(f"legit:{seed}:{onboard_day}:first_invoice_delay").randint(1, FIRST_INVOICE_MAX_DELAY)


def _acct(rng: random.Random) -> str:
    return str(rng.randint(10**9, 10**10 - 1))


def _routing(rng: random.Random) -> str:
    return str(rng.randint(10**8, 10**9 - 1))


def _initials(name: str) -> str:
    letters = "".join(w[0] for w in name.replace(",", " ").replace("-", " ").split() if w[:1].isalpha()).upper()
    return (letters or "VND")[:3]


async def inject(episode_id: str, seed: int, day: int) -> dict[str, int]:
    rng = random.Random(seed * 1009 + day)
    counts = {"invoices": 0, "purchase_orders": 0, "expenses": 0, "bank_lines": 0, "vendor_changes": 0, "new_vendors": 0}
    # a vendor onboarded this episode joins the generic traffic once it is GENERIC_MIN_AGE days old
    vendors = [
        dict(r)
        for r in await db.fetch(
            "SELECT * FROM vendors WHERE episode_id=$1 AND origin='sim' AND status='active' AND created_day <= $2 ORDER BY created_day, name, bank_account",
            episode_id,
            day - GENERIC_MIN_AGE,
        )
    ]
    employees = [
        dict(r)
        for r in await db.fetch(
            "SELECT * FROM employees WHERE episode_id=$1 AND origin='sim' AND status='active' ORDER BY start_day, name, bank_account", episode_id
        )
    ]
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

    # new vendors' first invoices (against their onboarding PO) come before the generic ones
    counts["invoices"] += await _new_vendor_first_invoices(episode_id, seed, day)

    # 3-6 invoices, mostly against open POs, a couple without (legit no-PO vendors exist).
    # A PO is billed once: POs that already have an invoice are skipped, and so are the POs of
    # vendors still inside their first-invoice window (that invoice comes from the step above).
    open_pos = [
        dict(r)
        for r in await db.fetch(
            "SELECT po.* FROM purchase_orders po JOIN vendors v ON v.id=po.vendor_id "
            "WHERE po.episode_id=$1 AND po.status='open' AND po.origin='sim' AND po.created_day < $2 AND v.created_day < $3 "
            "AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.po_id=po.id) "
            "ORDER BY po.created_day, po.amount, po.description",
            episode_id,
            day,
            day - FIRST_INVOICE_MAX_DELAY,
        )
    ]
    text = _rng(seed, day, "text")
    for _ in range(rng.randint(3, 6)):
        if open_pos and rng.random() < 0.8:
            po = open_pos.pop(rng.randrange(len(open_pos)))
            vid, po_id = po["vendor_id"], po["id"]
            amount = round(float(po["amount"]) * rng.uniform(0.97, 1.03), 2)  # small legit variance
            desc = _line_desc(text, None, po["description"])
        else:
            v = rng.choice(vendors)
            vid, po_id = v["id"], None
            amount = round(rng.uniform(150, 2500), 2)
            desc = _line_desc(text, v.get("category"))
        await db.execute(
            "INSERT INTO invoices (id, episode_id, vendor_id, po_id, amount, invoice_number, line_items, received_day, due_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'sim')",
            db.new_id("inv"),
            episode_id,
            vid,
            po_id,
            amount,
            f"INV-{rng.randint(10000, 99999)}",
            [{"desc": desc, "amount": amount}],
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
        category = rng.choice(["travel", "meals", "software", "supplies"])
        await db.execute(
            "INSERT INTO expenses (id, episode_id, employee_id, amount, category, memo, submitted_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,'sim')",
            db.new_id("exp"),
            episode_id,
            e["id"],
            amount,
            category,
            text.choice(EXPENSE_MEMOS[category]).format(n=text.randint(2, 6)),
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

    # false-positive bait: a brand-new vendor with a real PO, and a legit bank-account change.
    # After the invoices, so a bank change can come from a vendor whose invoices from today are open.
    if new_vendor_scheduled(seed, day):
        await _onboard_vendor(episode_id, seed, day)
        counts["new_vendors"] += 1
        counts["purchase_orders"] += 1
    if bank_change_scheduled(seed, day) and await _bank_change(episode_id, seed, day):
        counts["vendor_changes"] += 1
    return counts


async def _onboard_vendor(episode_id: str, seed: int, day: int) -> None:
    """A legit new vendor (created_day=day) and its first PO. Its invoice comes in a day or two later."""
    rng = _rng(seed, day, "new_vendor")
    fake = Faker()
    fake.seed_instance(f"legit:{seed}:{day}:new_vendor")
    taken = {r["name"] for r in await db.fetch("SELECT name FROM vendors WHERE episode_id=$1", episode_id)}
    name = fake.company()
    while name in taken:
        name = fake.company()
    category = rng.choice(CATEGORIES)
    vid = db.new_id("ven")
    await db.execute(
        "INSERT INTO vendors (id, episode_id, name, ein, bank_account, bank_routing, address, category, created_day, origin, created_by) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'sim',$10)",
        vid,
        episode_id,
        name,
        f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}",
        _acct(rng),
        _routing(rng),
        fake.address().replace("\n", ", "),
        category,
        day,
        ONBOARDED_BY,
    )
    await db.execute(
        "INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, description, created_day, origin) VALUES ($1,$2,$3,$4,$5,$6,'sim')",
        db.new_id("po"),
        episode_id,
        vid,
        round(rng.uniform(1500, 9000), 2),  # first engagement, above the $1,000 line the vendor-age rule watches
        rng.choice([f"{category} — initial order", f"{category} — trial engagement", f"{category} — onboarding order"]),
        day,
    )


async def _new_vendor_first_invoices(episode_id: str, seed: int, day: int) -> int:
    """First invoice, against the onboarding PO, from each legit vendor onboarded first_invoice_delay days ago."""
    rows = await db.fetch(
        "SELECT v.id AS vendor_id, v.name, v.category, v.created_day, po.id AS po_id, po.amount FROM vendors v "
        "JOIN purchase_orders po ON po.vendor_id=v.id AND po.created_day=v.created_day AND po.origin='sim' AND po.status='open' "
        "WHERE v.episode_id=$1 AND v.origin='sim' AND v.created_day BETWEEN $2 AND $3 "
        "AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.po_id=po.id) "
        "ORDER BY v.created_day, v.name, po.amount",
        episode_id,
        max(0, day - FIRST_INVOICE_MAX_DELAY),
        day - 1,
    )
    n = 0
    seen: set[str] = set()
    for r in rows:
        if r["vendor_id"] in seen or day - r["created_day"] != first_invoice_delay(seed, r["created_day"]):
            continue
        seen.add(r["vendor_id"])
        rng = _rng(seed, day, f"first_invoice:{r['created_day']}")
        amount = round(float(r["amount"]) * rng.uniform(0.97, 1.03), 2)
        await db.execute(
            "INSERT INTO invoices (id, episode_id, vendor_id, po_id, amount, invoice_number, line_items, received_day, due_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'sim')",
            db.new_id("inv"),
            episode_id,
            r["vendor_id"],
            r["po_id"],
            amount,
            f"{_initials(r['name'])}-{rng.randint(1000, 9999)}",
            [{"desc": _line_desc(_rng(seed, day, f"first_invoice_text:{r['created_day']}"), r["category"]), "amount": amount}],
            day,
            day + 30,
        )
        n += 1
    return n


async def _bank_change(episode_id: str, seed: int, day: int) -> bool:
    """A legit bank_account change request from an established vendor; old_value = its current account."""
    rng = _rng(seed, day, "bank_change")
    cutoff = day - ESTABLISHED_AGE
    candidates = [
        dict(r)
        for r in await db.fetch(
            "SELECT v.*, EXISTS (SELECT 1 FROM invoices i WHERE i.vendor_id=v.id AND i.status = ANY($3::text[])) AS has_open "
            "FROM vendors v WHERE v.episode_id=$1 AND v.origin='sim' AND v.status='active' AND v.created_day <= $2 "
            "AND NOT EXISTS (SELECT 1 FROM vendor_changes ch WHERE ch.vendor_id=v.id AND (ch.status='pending' OR ch.requested_day >= $2)) "
            "ORDER BY v.created_day, v.name, v.bank_account",
            episode_id,
            cutoff,
            OPEN_INVOICE_STATUSES,
        )
    ]
    if not candidates:
        return False
    want_open = rng.random() < BANK_CHANGE_OPEN_SHARE
    v = rng.choice([c for c in candidates if c["has_open"] == want_open] or candidates)
    new_account = _acct(rng)
    while new_account == v["bank_account"]:
        new_account = _acct(rng)
    await db.execute(
        "INSERT INTO vendor_changes (id, episode_id, vendor_id, field, old_value, new_value, justification, requested_day, origin) "
        "VALUES ($1,$2,$3,'bank_account',$4,$5,$6,$7,'sim')",
        db.new_id("vch"),
        episode_id,
        v["id"],
        v["bank_account"],
        new_account,
        rng.choice(BANK_CHANGE_REASONS).format(bank=rng.choice(BANKS)),
        day,
    )
    return True


def _po_desc(rng: random.Random, v: dict[str, Any]) -> str:
    cat = v.get("category") or "services"
    return rng.choice([f"{cat} — monthly", f"{cat} — project work", f"{cat} — replenishment", f"{cat} — Q4 order"])
