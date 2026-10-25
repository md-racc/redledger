"""Bounded playbook data, never executable rules or model-supplied instructions."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from agentkit.models import GateRequest, ReflectRequest, ReflectResponse

from . import rules

LEARNED_FOR = {
    "ghost_vendor": {"learned:young_vendor_any_amount"},
    "duplicate_invoice": {"learned:duplicate_amount_loose"},
    "bank_swap": {"learned:bank_change_any_amount"},
    "threshold_split": {"learned:near_threshold_wide", "learned:young_vendor_any_amount"},
}
KNOWN = set().union(*LEARNED_FOR.values())


def _ids(value: object) -> set[str]:
    return {item for item in value[:64] if isinstance(item, str) and item in KNOWN} if isinstance(value, list) else set()


# A baseline rule is retired for a lineage only after a generation review shows sustained
# legit-only fire (#133): on_legit at or above this floor with on_red still zero.
BASELINE_RETIRE_MIN_ON_LEGIT = 3


def _baseline_ids(value: object) -> set[str]:
    return {item for item in value[:64] if isinstance(item, str) and item in rules.RETIREABLE_RULE_IDS} if isinstance(value, list) else set()


def baseline_retired(content: dict) -> frozenset[str]:
    return frozenset(_baseline_ids(content.get("retired_baseline")))


def _band(content: dict) -> Decimal:
    try:
        return min(Decimal(".95"), max(Decimal(".80"), rules.money(content.get("near_band", ".95"))))
    except ValueError:
        return Decimal(".95")


def reflect(req: ReflectRequest) -> ReflectResponse:
    """Learn only from the supplied finished-generation review; no ledger writes."""
    content = deepcopy(req.playbook.content)
    marker = [req.lineage_id, req.generation, req.episode_id]
    if content.get("blue_review") == marker:
        return ReflectResponse(ok=True, rationale="Review already applied; playbook kept.")
    items = req.review.get("items", [])
    if not isinstance(items, list) or len(items) > 2000:
        return ReflectResponse(ok=False, rationale="Review items unavailable; playbook kept.")
    learned, retired, band = _ids(content.get("learned")), _ids(content.get("retired")), _band(content)
    retired_baseline = _baseline_ids(content.get("retired_baseline"))
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        attack_id, scheme = item.get("attack_id"), item.get("scheme_id")
        if (
            item.get("kind") == "attack"
            and isinstance(attack_id, str)
            and 0 < len(attack_id) <= 200
            and attack_id not in seen
            and isinstance(scheme, str)
            and scheme in LEARNED_FOR
            and item.get("outcome") in ("extracted", "partial")
        ):
            seen.add(attack_id)
            learned.update(LEARNED_FOR[scheme])
            if scheme == "threshold_split":
                band = max(Decimal(".80"), band - Decimal(".05"))
        if item.get("kind") == "false_positive" and isinstance(item.get("by"), dict):
            retired.update(_ids(item["by"].get("rules_fired")))
    statistics = req.review.get("rules", [])
    for row in statistics[:2000] if isinstance(statistics, list) else []:
        if isinstance(row, dict) and type(row.get("on_legit")) is int and row["on_legit"] > 0:
            retired.update(_ids([row.get("rule_id")]))
        if (
            isinstance(row, dict)
            and type(row.get("on_legit")) is int
            and row["on_legit"] >= BASELINE_RETIRE_MIN_ON_LEGIT
            and type(row.get("on_red")) is int
            and row["on_red"] == 0
        ):
            retired_baseline.update(_baseline_ids([row.get("rule_id")]))
    enabled = learned - retired
    if (
        enabled == _ids(content.get("learned"))
        and retired == _ids(content.get("retired"))
        and retired_baseline == _baseline_ids(content.get("retired_baseline"))
        and band == _band(content)
    ):
        return ReflectResponse(ok=True, rationale="No control change justified; playbook kept.")
    content.update(learned=sorted(enabled), retired=sorted(retired), near_band=float(band), blue_review=marker)
    if retired_baseline or "retired_baseline" in content:
        content["retired_baseline"] = sorted(retired_baseline)
    newly = sorted(retired_baseline - _baseline_ids(req.playbook.content.get("retired_baseline")))
    rationale = f"Retained {len(enabled)} learned review controls; retired {len(retired)} controls with legitimate-item impact."
    if newly:
        rationale += f" Retired baseline rules after legit-only fire: {', '.join(newly)}."
    return ReflectResponse(ok=True, playbook=content, rationale=rationale)


def evaluate(req: GateRequest, content: dict) -> list[rules.RuleHit]:
    """Fixed predicates use validated gate evidence, not disclosed entity IDs."""
    if req.action not in rules.INVOICE_ACTIONS:
        return []
    try:
        rules.validate(req)
        enabled = _ids(content.get("learned")) - _ids(content.get("retired"))
        amount, inv = rules.money(req.amount), req.context["invoice"]
        paid = req.context["vendor_paid_invoices"]
        age = rules._vendor_age(req)
        candidates = {
            "learned:young_vendor_any_amount": (
                age < 7 and not inv.get("po_id") and not paid,
                "New vendor has no PO or paid history; independently verify onboarding even for small payments.",
            ),
            "learned:near_threshold_wide": (
                age < 7
                and not inv.get("po_id")
                and not paid
                and rules.approval_threshold() * _band(content) <= amount < rules.approval_threshold() * Decimal(".95"),
                "A widened exposure band applies to an unestablished vendor without PO or paid history; independently verify.",
            ),
            "learned:duplicate_amount_loose": (
                any(p["id"] != inv["id"] and p["invoice_number"] != inv["invoice_number"] and abs(rules.money(p["amount"]) - amount) <= 1 for p in paid),
                "Amount closely matches a paid invoice under a different number; verify document identity.",
            ),
            "learned:bank_change_any_amount": (
                req.action == "invoices.pay"
                and any(
                    ch["status"] == "approved"
                    and rules._actual_bank_change(ch)
                    and 0 <= req.day - rules._day(ch.get("resolved_day") if ch.get("resolved_day") is not None else ch["requested_day"]) <= 14
                    for ch in req.context["vendor_recent_changes"]
                ),
                "Payment follows a recent destination change; independently verify even for small payments.",
            ),
        }
        return [rules.RuleHit(key, 2, detail, "review", "learned") for key, (fires, detail) in candidates.items() if key in enabled and fires]
    except (ValueError, KeyError, TypeError):
        return [rules.RuleHit("learned:verification_unavailable", 0, "Learned control evidence is unavailable.", "unavailable")]
