"""Deterministic findings and neutral model projection over one bounded public snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from agentkit.ledger_client import LedgerClient
from gate.rules import BANK_FIELDS, approval_threshold, duplicate_pair

from .models import Coverage, Evidence, Finding, Snapshot
from .snapshot import collect_snapshot as collect_rows

MAX_FINDINGS = 20


async def collect_snapshot(ledger: LedgerClient, episode_id: str, day: int, inputs: Any = None) -> Snapshot:
    snapshot = await collect_rows(ledger, episode_id, day, inputs)
    # CPU-only evidence processing must not monopolize the gate's event loop.
    await asyncio.to_thread(derive_findings, snapshot)
    return snapshot


def _complete(snapshot: Snapshot, *datasets: str) -> bool:
    statuses = {c.dataset: c.status for c in snapshot.coverage}
    return all(statuses.get(dataset) == "complete" for dataset in datasets)


def _finding(snapshot: Snapshot, code: str, kind: str, entity_id: str, vendor_id: str | None, severity: str, evidence: list[Evidence]) -> Finding:
    fingerprint = hashlib.sha256(json.dumps([snapshot.episode_id, code, kind, entity_id], separators=(",", ":")).encode()).hexdigest()[:24]
    reason = f"[blue:{fingerprint}] " + " ".join(e.fact for e in evidence)
    return Finding(
        id=fingerprint, code=code, entity_type=kind, entity_id=entity_id, vendor_id=vendor_id, severity=severity, evidence=tuple(evidence), reason=reason
    )


class PaidInvoiceIndex:
    """Bounded O(n log n) candidate lookup, with duplicate_pair as the final policy."""

    def __init__(self, invoices: list[dict[str, Any]]):
        self.exact: dict[str, list[dict]] = defaultdict(list)
        self.by_number_po: dict[tuple[str, str], list[tuple[Decimal, str, dict]]] = defaultdict(list)
        self.by_stem_po: dict[tuple[str, str], list[tuple[Decimal, str, dict]]] = defaultdict(list)
        for row in invoices:
            number = row["invoice_number"].strip().casefold()
            # Two exact identities suffice to exclude a current invoice's own row.
            if len(self.exact[number]) < 2:
                self.exact[number].append(row)
            if row.get("po_id"):
                item = (row["amount"], row["id"], row)
                self.by_number_po[(number, row["po_id"])].append(item)
                if number and number[-1].isalpha():
                    self.by_stem_po[(number[:-1], row["po_id"])].append(item)
        for index in (self.by_number_po, self.by_stem_po):
            for values in index.values():
                values.sort(key=lambda item: (item[0], item[1]))

    def duplicates(self, row: dict[str, Any]) -> bool:
        number = row["invoice_number"].strip().casefold()
        if any(duplicate_pair(row, paid) for paid in self.exact.get(number, [])):
            return True
        po_id = row.get("po_id")
        if not po_id:
            return False
        groups = [self.by_stem_po.get((number, po_id), [])]
        if number and number[-1].isalpha():
            groups.append(self.by_number_po.get((number[:-1], po_id), []))
        for group in groups:
            lower = row["amount"] - Decimal(".05")
            position = bisect_left(group, (lower, ""))
            for amount, _, paid in group[position : position + 2]:
                if amount <= row["amount"] + Decimal(".05") and duplicate_pair(row, paid):
                    return True
        return False


def derive_findings(snapshot: Snapshot) -> None:
    data = snapshot.datasets
    vendors = {v["id"]: v for v in data.get("vendors", [])}
    invoices = data.get("invoices", [])
    if any(
        not isinstance(row.get("bank_account"), str) or not row["bank_account"].strip() for dataset in ("vendors", "employees") for row in data.get(dataset, [])
    ):
        snapshot.coverage.append(Coverage(dataset="account_control", status="partial", detail="Some account comparisons are unavailable."))
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    for inv in invoices:
        by_vendor[inv["vendor_id"]].append(inv)
    open_exposure_by_vendor: dict[str, Decimal] = defaultdict(Decimal)
    invoice_vendors = {}
    for inv in invoices:
        invoice_vendors[inv["id"]] = inv["vendor_id"]
        if inv["status"] in {"pending", "matched", "approved"}:
            open_exposure_by_vendor[inv["vendor_id"]] += inv["amount"]
    paid_today_ids = {p["invoice_id"] for p in data.get("payments", []) if p.get("invoice_id") and p.get("paid_day") == snapshot.day}
    material_paid_vendors = {
        invoice_vendors[p["invoice_id"]]
        for p in data.get("payments", [])
        if p.get("invoice_id") in invoice_vendors and p.get("paid_day") == snapshot.day and p["amount"] > 2500
    }
    findings = []
    try:
        threshold = approval_threshold()
    except ValueError:
        snapshot.coverage.append(Coverage(dataset="policy", status="unavailable", detail="Approval threshold invalid."))
        threshold = None

    for vendor_id, invs in by_vendor.items():
        vendor = vendors.get(vendor_id)
        paid = [inv for inv in invs if inv["status"] == "paid"]
        paid_index = PaidInvoiceIndex(paid)
        current = [
            inv
            for inv in invs
            if inv["status"] != "rejected"
            and (inv["received_day"] == snapshot.day or inv["id"] in paid_today_ids or inv["status"] in {"pending", "matched", "approved"})
        ]
        for inv in current:
            if paid_index.duplicates(inv):
                findings.append(
                    _finding(
                        snapshot,
                        "duplicate_invoice",
                        "invoice",
                        inv["id"],
                        vendor_id,
                        "high",
                        [
                            Evidence(family="integrity", fact="Invoice identity duplicates a paid invoice for this vendor.", substantive=True),
                        ],
                    )
                )
        near = [
            inv
            for inv in current
            if inv["received_day"] == snapshot.day and threshold is not None and threshold * Decimal(".90") <= inv["amount"] < threshold and not inv["po_id"]
        ]
        if len(near) >= 3 and sum((inv["amount"] for inv in near), Decimal(0)) >= threshold:
            findings.append(
                _finding(
                    snapshot,
                    "same_day_split",
                    "vendor",
                    vendor_id,
                    vendor_id,
                    "medium",
                    [
                        Evidence(
                            family="structure",
                            fact="At least three same-day, near-threshold invoices lack associated POs and together exceed the approval threshold.",
                        ),
                    ],
                )
            )
        if vendor and threshold is not None and 0 <= snapshot.day - vendor["created_day"] < 7 and _complete(snapshot, "invoices", "vendors", "payments"):
            exposed = [inv for inv in current if not inv["po_id"]]
            exposure_ids = {inv["id"] for inv in exposed}
            prior_paid = [inv for inv in paid if inv["id"] not in exposure_ids]
            if not prior_paid and sum((inv["amount"] for inv in exposed), Decimal(0)) >= threshold * Decimal(".95"):
                findings.append(
                    _finding(
                        snapshot,
                        "unverified_vendor_exposure",
                        "vendor",
                        vendor_id,
                        vendor_id,
                        "medium",
                        [
                            Evidence(
                                family="authorization",
                                fact="A new vendor has near-threshold or larger exposure without independent paid history or associated POs.",
                            ),
                        ],
                    )
                )

    destination_failures = 0
    for change in data.get("changes", []):
        if change["vendor_id"] not in vendors or change.get("status") not in {"pending", "approved"} or change.get("field") not in BANK_FIELDS:
            continue
        old, new = change.get("old_value"), change.get("new_value")
        if not isinstance(old, str) or not isinstance(new, str) or not old.strip() or not new.strip():
            destination_failures += 1
            continue
        when = change.get("resolved_day")
        when = change["requested_day"] if when is None else when
        if isinstance(when, bool) or not isinstance(when, int) or when > snapshot.day:
            destination_failures += 1
            continue
        if not 0 <= snapshot.day - when <= 14 or old.strip() == new.strip():
            continue
        open_exposure = open_exposure_by_vendor[change["vendor_id"]]
        material_paid = change["vendor_id"] in material_paid_vendors
        if open_exposure > 0 or material_paid:
            findings.append(
                _finding(
                    snapshot,
                    "bank_change_exposure",
                    "vendor_change",
                    change["id"],
                    change["vendor_id"],
                    "medium",
                    [
                        Evidence(family="destination", fact="An actual recent destination change overlaps open invoices or a material payment today."),
                    ],
                )
            )

    if destination_failures:
        snapshot.coverage.append(
            Coverage(
                dataset="destination_control",
                status="partial",
                omitted=destination_failures,
                detail="Some destination comparisons or timings are unavailable.",
            )
        )

    for employee in data.get("employees", []):
        if employee["hr_record"] is False:
            findings.append(
                _finding(
                    snapshot,
                    "no_hr_record",
                    "employee",
                    employee["id"],
                    None,
                    "high",
                    [
                        Evidence(family="identity", fact="Employee explicitly lacks an HR onboarding record.", substantive=True),
                    ],
                )
            )

    bank_groups: dict[str, list[dict]] = defaultdict(list)
    names: Counter = Counter()
    for vendor in vendors.values():
        account = vendor.get("bank_account")
        if isinstance(account, str) and account.strip():
            bank_groups[account.strip()].append(vendor)
        name = vendor.get("name")
        if isinstance(name, str):
            normalized = "".join(ch for ch in name.casefold() if ch.isalnum())
            if normalized:
                names[normalized] += 1
    snapshot.name_hint_groups = sum(count > 1 for count in names.values())
    for group in bank_groups.values():
        if len(group) > 1:
            for vendor in group:
                findings.append(
                    _finding(
                        snapshot,
                        "account_collision",
                        "vendor",
                        vendor["id"],
                        vendor["id"],
                        "medium",
                        [
                            Evidence(family="identity", fact="Two or more vendors share a payment account; ownership requires independent verification."),
                        ],
                    )
                )
    for employee in data.get("employees", []):
        if isinstance(employee.get("bank_account"), str) and employee["bank_account"].strip() in bank_groups:
            findings.append(
                _finding(
                    snapshot,
                    "employee_account_collision",
                    "employee",
                    employee["id"],
                    None,
                    "medium",
                    [
                        Evidence(family="identity", fact="Employee and vendor share a payment account; ownership requires independent verification."),
                    ],
                )
            )
    # Prioritize substantive findings over hints; cap both model visibility and automated mutations.
    findings.sort(key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f.severity], f.code, f.entity_id))
    snapshot.total_findings = len(findings)
    snapshot.findings = findings[:MAX_FINDINGS]
    if len(findings) > MAX_FINDINGS:
        snapshot.coverage.append(
            Coverage(
                dataset="findings",
                status="truncated",
                processed=MAX_FINDINGS,
                omitted=len(findings) - MAX_FINDINGS,
                detail="Additional findings need human review.",
            )
        )


def model_view(snapshot: Snapshot) -> dict[str, Any]:
    """No source prose, names, invoice numbers, bank details, actor, or nested logs."""
    return {
        "day": snapshot.day,
        "reviewed": {name: len(rows) for name, rows in snapshot.datasets.items()},
        "coverage": [c.model_dump() for c in snapshot.coverage],
        "findings": [finding.model_dump() for finding in snapshot.findings],
        "leads_corroborated_as_entities": snapshot.leads_reviewed,
        "activity": [
            {"action": action, "count": count} for action, count in sorted(Counter(row["action"] for row in snapshot.datasets.get("activity", [])).items())
        ],
        "scope_note": "Unpaginated public APIs; row caps do not bound HTTP response bytes or prove upstream completeness.",
    }


def benford(snapshot: Snapshot) -> dict[str, Any]:
    digits = Counter()
    for inv in snapshot.datasets.get("invoices", []):
        if inv["received_day"] == snapshot.day and inv["amount"] > 0:
            digits[str(inv["amount"].as_tuple().digits[0])] += 1
    n = sum(digits.values())
    deviation = sum(abs(digits.get(str(d), 0) / n - math.log10(1 + 1 / d)) for d in range(1, 10)) if n else 0.0
    return {"n": n, "observed": dict(digits), "deviation": round(deviation, 3), "hint_only": True, "mutation_authority": False}
