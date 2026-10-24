"""Policy smoke coverage; the full regression matrix follows in the dependent review."""

from agentkit.models import GateRequest
from gate import engine
from gate.rules import evaluate


def req(action: str, amount: float | None, ctx: dict, day: int = 5, mode: str = "enforce") -> GateRequest:
    context = {
        "vendor": {"id": "v", "created_day": -400, "status": "active"},
        "invoice": {"id": "i", "vendor_id": "v", "amount": amount, "invoice_number": "B", "po_id": None},
        "po": None,
        "vendor_paid_invoices": [],
        "vendor_recent_changes": [],
    }
    context.update(ctx)
    return GateRequest(
        idempotency_key=f"k-{action}-{amount}-{day}-{mode}",
        episode_id="ep",
        day=day,
        controller_mode=mode,
        agent="green",
        action=action,
        amount=amount,
        context=context,
    )


def test_new_vendor_large_invoice_hits():
    hits = evaluate(req("invoices.pay", 4920, {"vendor": {"id": "v", "created_day": 5, "status": "active"}}))
    assert {h.id for h in hits} >= {"vendor_age_lt_7d", "near_threshold", "unverified_vendor_exposure"}


def test_clean_invoice_allows():
    hits = evaluate(
        req(
            "invoices.pay",
            1200,
            {"vendor_paid_invoices": [{"id": "p", "vendor_id": "v", "status": "paid", "amount": 1150, "po_id": "po", "invoice_number": "A"}]},
        )
    )
    assert hits == []


async def test_engine_blocks_on_verified_exposure_and_caches():
    r = req("invoices.pay", 4920, {"vendor": {"id": "v", "created_day": 5, "status": "active"}})
    a = await engine.decide(r)
    assert a.verdict == "block" and "vendor_age_lt_7d" in a.rules_fired
    assert await engine.decide(r) == a


async def test_single_low_hit_allows_in_every_mode():
    for mode in ("off", "shadow", "enforce"):
        assert (await engine.decide(req("invoices.pay", 4800, {}, mode=mode))).verdict == "allow"
