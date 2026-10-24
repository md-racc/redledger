"""Owner: Dev M. Rules are pure functions: test them directly."""

from agentkit.models import GateRequest
from gate import engine
from gate.rules import evaluate


def req(action: str, amount: float | None, ctx: dict, day: int = 5, mode: str = "enforce") -> GateRequest:
    return GateRequest(
        idempotency_key=f"k-{action}-{amount}-{day}", episode_id="ep", day=day, controller_mode=mode, agent="green", action=action, amount=amount, context=ctx
    )


def test_new_vendor_large_invoice_hits():
    hits = evaluate(req("invoices.pay", 4920.0, {"vendor": {"created_day": 5}, "vendor_paid_invoices": []}))
    assert {h.id for h in hits} >= {"vendor_age_lt_7d", "near_threshold"}


def test_clean_invoice_allows():
    hits = evaluate(
        req("invoices.pay", 1200.0, {"vendor": {"created_day": -400}, "vendor_paid_invoices": [{"amount": 1150, "po_id": "po", "invoice_number": "A"}]})
    )
    assert hits == []


async def test_engine_blocks_on_two_hits_and_caches():
    r = req("invoices.pay", 4920.0, {"vendor": {"created_day": 5}, "vendor_paid_invoices": []})
    a = await engine.decide(r)
    assert a.verdict == "block" and "vendor_age_lt_7d" in a.rules_fired
    b = await engine.decide(r)
    assert b == a


async def test_single_low_hit_escalates_in_enforce_allows_in_shadow():
    ctx = {"vendor": {"created_day": -400}, "vendor_paid_invoices": []}
    assert (await engine.decide(req("invoices.pay", 4800.0, ctx, mode="enforce"))).verdict == "escalate"
    assert (await engine.decide(req("invoices.pay", 4800.0, ctx, mode="shadow", day=6))).verdict == "allow"
