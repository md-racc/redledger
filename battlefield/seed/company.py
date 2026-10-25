"""Seed Meridian Components for a new episode. Owner: Dev Ad (plumbing) / Dev M (realism).

Deterministic from `seed`. Produces 90 days of clean history: vendors, employees, POs, paid
invoices, payments, bank feed, GL. Everything origin='sim'. Dev M: make this look like a real
QuickBooks export — vendor categories, recurring monthly vendors, realistic amounts.

`COMPANY` is the one source of the company's identity: the /fe snapshot and anything else that
names the company read it. Vendor names and line descriptions are themed for an electronics
components distributor (`vendor_name`, `line_item`); legit traffic draws from the same generator.
Names and line text come from their own RNG streams, so the categories, amounts, days and bank
details drawn from `random.Random(seed)` are exactly what they were before the theme.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from faker import Faker

from app import db


@dataclass(frozen=True)
class Company:
    name: str
    industry: str
    hq: str
    description: str


# Fictional, like every vendor below. Never swap in a real company's name.
COMPANY = Company(
    name="Meridian Components",
    industry="electronics components distribution",
    hq="Calder Bay, California",
    description="A mid-size electronics components distributor that buys from overseas manufacturers and resells to OEMs.",
)

# ---------------- themed vendor roster ----------------
# A vendor's kind is recoverable from its name (the descriptor in it), so later traffic can give it
# fitting line items without a schema change: see `vendor_kind`. Descriptors are unique across kinds.

_STEMS = [
    "Halvern", "Corvane", "Brenmoor", "Quillon", "Tessaly", "Ardent Ridge", "Kestrel Point", "Northvale",
    "Cobalt Reach", "Larkspur", "Thornbury", "Westerly", "Silvermere", "Ostley", "Pellham", "Granite Ford",
    "Ashgrove", "Calder", "Harrow Lane", "Ivel", "Juniper Flats", "Kittering", "Lowmoor", "Mossbank",
    "Nettleford", "Orrin", "Prentiss Hill", "Quarry Gate", "Rushford", "Stannard", "Upland Mesa", "Verran",
    "Yarrow", "Brightwater", "Cedar Notch", "Dunmore", "Elmstead", "Foxhollow", "Galloway", "Highcastle",
]  # fmt: skip
_ENTITIES = [" Inc.", " LLC", " Corp.", " Co.", ""]
_CN_CITIES = ["Shenzhen", "Dongguan", "Suzhou", "Xiamen", "Ningbo"]
_CN_STEMS = ["Qiyuan", "Lianfeng", "Shengtai", "Kaiwei", "Yaxin", "Boheng", "Xinrui", "Dexun", "Tongyao", "Ruixin", "Haoyun", "Jiacheng"]
_TW_STEMS = ["Chengyu", "Weilun", "Hsinyao", "Kuanyi", "Liyuan", "Tsunghe"]
_TW_CITIES = ["Hsinchu", "Taoyuan", "Taichung"]
_MY_STEMS = ["Seri Bayu", "Bukit Jaya", "Lumut Tech", "Perdana Mas"]


@dataclass(frozen=True)
class VendorKind:
    category: str  # the vendors.category value (unchanged set: CATEGORIES)
    descriptors: tuple[str, ...]  # one of these appears in every name of this kind
    overseas: bool  # half of these are overseas manufacturers / forwarders
    lines: tuple[str, ...]  # invoice and PO line descriptions


KINDS: dict[str, VendorKind] = {
    "pcb": VendorKind(
        "raw_materials",
        ("Circuits", "PCB", "Circuit Board", "Printed Circuit"),
        True,
        (
            "4-layer PCB, 500 pcs",
            "2-layer FR-4 PCB, 1,000 pcs",
            "6-layer HDI PCB, prototype run of 50",
            "PCB tooling and e-test fixture",
            "4-layer PCB, ENIG finish, 250 pcs",
        ),
    ),
    "passives": VendorKind(
        "raw_materials",
        ("Passive Components", "Capacitor", "Resistor", "Magnetics"),
        True,
        (
            "0402 MLCC capacitors, 10k reel",
            "0603 thick-film resistors, 5k reel",
            "Aluminium electrolytic capacitors, 2k pcs",
            "Power inductors, 3k reel",
            "Ferrite beads 0603, 10k reel",
        ),
    ),
    "semis": VendorKind(
        "raw_materials",
        ("Semiconductor Supply", "Semi Sourcing", "Silicon Trading", "IC Brokerage"),
        True,
        (
            "32-bit MCUs, 2,500 pcs (broker lot)",
            "LDO regulators SOT-23, 3k reel",
            "N-channel MOSFETs, tape and reel",
            "Op-amps SOIC-8, 2,500 pcs",
            "Gate drivers, allocation buy",
        ),
    ),
    "connectors": VendorKind(
        "raw_materials",
        ("Connector", "Cable Assemblies", "Wire & Cable", "Interconnect"),
        True,
        (
            "USB-C receptacles, 5k reel",
            "Board-to-board connectors, 2k pcs",
            "Custom wire harness, 300 pcs",
            "M12 cable assemblies, 200 pcs",
            "Pin headers 2.54 mm, 10k pcs",
        ),
    ),
    "contract_mfg": VendorKind(
        "raw_materials",
        ("Contract Manufacturing", "EMS", "Electronics Assembly", "Box Build"),
        True,
        ("SMT assembly, 500 boards", "Box build and functional test, 120 units", "Conformal coating, 400 boards", "NPI pilot run, 50 units"),
    ),
    "freight": VendorKind(
        "logistics",
        ("Freight", "Logistics", "Forwarding", "Shipping"),
        True,
        (
            "Ocean freight, 1x40ft, Yantian to Long Beach",
            "Air freight, 320 kg, HKG to SFO",
            "Drayage, port to warehouse",
            "LCL ocean freight, 6 cbm",
            "Domestic LTL, 4 pallets",
        ),
    ),
    "customs": VendorKind(
        "logistics",
        ("Customs Brokerage", "Customs Services", "Trade Compliance"),
        False,
        ("Customs entry and ISF filing", "Import duties and broker fee", "Tariff classification review", "Customs bond renewal"),
    ),
    "test_lab": VendorKind(
        "professional",
        ("Test Labs", "Calibration", "Metrology", "Reliability Testing"),
        False,
        (
            "Counterfeit screening, X-ray and decap, 3 lots",
            "Oscilloscope calibration, 6 units",
            "Solderability testing, 3 lots",
            "ESD audit and wrist-strap tester calibration",
        ),
    ),
    "professional": VendorKind(
        "professional",
        ("CPA Group", "Advisory", "Legal Partners", "Tax & Audit", "Consulting", "Staffing"),
        False,
        ("Monthly bookkeeping review", "Quarterly tax advisory", "Export compliance legal review", "Temporary warehouse staff, 2 weeks"),
    ),
    "esd_packaging": VendorKind(
        "office",
        ("ESD Supply", "Packaging", "Static Control", "Reel & Tray"),
        False,
        (
            "ESD shielding bags, 5k",
            "Moisture barrier bags and desiccant",
            "Anti-static reel boxes, 200",
            "ESD wrist straps and mats",
            "Carrier tape and cover tape",
        ),
    ),
    "office": VendorKind(
        "office",
        ("Office Supply", "Office Products", "Business Supply"),
        False,
        ("Office supplies", "Printer toner and paper", "Break-room supplies", "Shipping labels and printer ribbons"),
    ),
    "facilities": VendorKind(
        "facilities",
        ("Facility Services", "Building Services", "Janitorial", "HVAC", "Property Services", "Warehouse Systems"),
        False,
        ("Warehouse janitorial", "HVAC service, warehouse", "Forklift maintenance", "Pallet racking inspection", "Security monitoring"),
    ),
    "it": VendorKind(
        "it",
        ("Software", "Cloud", "Networks", "IT Services", "Data Systems"),
        False,
        ("ERP subscription", "Inventory management SaaS", "Managed network support", "Laptop refresh, 6 units", "EDI connection fees"),
    ),
    "marketing": VendorKind(
        "marketing",
        ("Media", "Marketing", "Trade Show Services", "Creative"),
        False,
        ("Trade show booth and shipping", "Line card printing", "Distributor catalog listing fee", "Web storefront ads"),
    ),
}
_KINDS_BY_CATEGORY: dict[str, list[str]] = {}
for _kind, _spec in KINDS.items():
    _KINDS_BY_CATEGORY.setdefault(_spec.category, []).append(_kind)


def _kinds(category: str | None) -> list[str]:
    return _KINDS_BY_CATEGORY.get(category or "", _KINDS_BY_CATEGORY["professional"])


def _overseas_name(rng: random.Random, desc: str) -> str:
    where = rng.random()
    if where < 0.6:
        return f"{rng.choice(_CN_CITIES)} {rng.choice(_CN_STEMS)} {desc} Co., Ltd."
    if where < 0.85:
        return f"{rng.choice(_TW_STEMS)} {desc} Co., Ltd. ({rng.choice(_TW_CITIES)})"
    return f"{rng.choice(_MY_STEMS)} {desc} Sdn. Bhd."


def vendor_name(rng: random.Random, category: str | None, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """A plausible, fictional supplier name for `category` that is not in `taken`. Draws only from `rng`."""
    kinds = _kinds(category)
    for attempt in range(60):
        spec = KINDS[rng.choice(kinds)]
        desc = rng.choice(spec.descriptors)
        name = _overseas_name(rng, desc) if spec.overseas and rng.random() < 0.5 else f"{rng.choice(_STEMS)} {desc}{rng.choice(_ENTITIES)}"
        if attempt >= 40:  # only an exhausted name space gets here
            name = f"{name} {attempt - 38}"
        if name not in taken:
            return name
    raise RuntimeError(f"no free vendor name for category {category!r}")


def vendor_kind(name: str | None, category: str | None) -> str:
    """The kind a themed name was built as; any other name falls back to its category's first kind."""
    kinds = _kinds(category)
    return next((k for k in kinds if any(d in (name or "") for d in KINDS[k].descriptors)), kinds[0])


def line_item(rng: random.Random, category: str | None, vendor: str | None = None) -> str:
    """An invoice/PO line description that fits this vendor. Draws only from `rng`."""
    return rng.choice(KINDS[vendor_kind(vendor, category)].lines)


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
    names = random.Random(f"company:{seed}:vendor_names")  # own streams: the theme never moves an amount
    text = random.Random(f"company:{seed}:text")
    fake = Faker()
    Faker.seed(seed)

    vendors: list[dict] = []
    taken: set[str] = set()
    for _i in range(N_VENDORS):
        cat = rng.choice(CATEGORIES)
        name = vendor_name(names, cat, taken)
        taken.add(name)
        v = {
            "id": db.new_id("ven"),
            "name": name,
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
            item = line_item(text, v["category"], v["name"])
            po_id = db.new_id("po")
            await db.execute(
                "INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, description, created_day, status, origin) VALUES ($1,$2,$3,$4,$5,$6,'fulfilled','sim')",
                po_id,
                episode_id,
                v["id"],
                amount,
                f"{item} — monthly" if monthly else item,
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
                [{"desc": item, "amount": amount}],
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
            line_item(text, v["category"], v["name"]),
            -rng.randint(1, 6),
        )
