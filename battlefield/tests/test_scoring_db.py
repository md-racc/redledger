"""DB: attack outcome resolution and the episode Score."""

from __future__ import annotations

import httpx
import pytest

from agentkit.models import Score
from app import db
from app.config import settings
from app.main import app
from app.scoring import score
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


async def _attack(aid: str) -> dict:
    return dict(await db.fetchrow("SELECT outcome, amount_extracted, detected_day FROM attacks WHERE id=$1", aid))


async def _resolve(ep: str, day: int = 5) -> None:
    await score.resolve_attacks(ep, day)


# ---------- bank_swap (red vendor_changes) ----------


async def test_bank_swap_blocked_at_approve_is_caught(episode: str) -> None:
    vid = await f.vendor(episode)
    atk = await f.attack(episode, day=1, target_amount=12_000)
    ch = await f.change(episode, vid, day=1, status="blocked")
    await f.verdict(episode, "vendor_change", ch, verdict="block", day=2)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 2}
    s = await score.compute(episode)
    assert s["dollars_blocked"] == 12_000
    assert s["dollars_extracted"] == 0
    assert s["attacks_caught"] == 1
    assert s["detection_latency_days"] == 1.0


async def test_bank_swap_rejected_or_frozen_counts_as_blocked(episode: str) -> None:
    v1 = await f.vendor(episode)
    v2 = await f.vendor(episode, status="frozen")
    a1 = await f.attack(episode, day=1, target_amount=5_000)
    a2 = await f.attack(episode, day=3, target_amount=7_000)
    await f.change(episode, v1, day=1, status="rejected", resolved_day=1)
    await f.change(episode, v2, day=3, status="pending")  # still pending, but the vendor is frozen
    await f.flag(episode, "vendor", v2, day=3)
    await _resolve(episode)
    assert (await _attack(a1))["outcome"] == "blocked"
    assert await _attack(a2) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 3}
    assert (await score.compute(episode))["dollars_blocked"] == 12_000


async def test_bank_swap_pending_change_is_pending_then_flagged(episode: str) -> None:
    vid = await f.vendor(episode)
    atk = await f.attack(episode, day=1)
    ch = await f.change(episode, vid, day=1)
    await _resolve(episode)
    assert (await _attack(atk))["outcome"] == "pending"
    await f.flag(episode, "vendor_change", ch, day=2)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "flagged", "amount_extracted": 0, "detected_day": 2}
    assert (await score.compute(episode))["dollars_blocked"] == 0


async def test_bank_swap_approved_without_payment_is_pending(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1)
    await f.change(episode, vid, day=1, status="approved", resolved_day=2)
    # paid before the swap was approved, and paid to another account: neither counts
    i1 = await f.invoice(episode, vid, status="paid")
    await f.payment(episode, i1, amount=900, to_account="ACCT-RED", day=1)
    i2 = await f.invoice(episode, vid, status="paid")
    await f.payment(episode, i2, amount=800, to_account="ACCT-OLD", day=3)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "pending", "amount_extracted": 0, "detected_day": None}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 0 and s["dollars_blocked"] == 0


async def test_bank_swap_approved_and_paid_is_extracted(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1, target_amount=4_000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=2)
    i1 = await f.invoice(episode, vid, amount=1500, status="paid")
    await f.payment(episode, i1, amount=1500, to_account="ACCT-RED", day=2)
    i2 = await f.invoice(episode, vid, amount=2500, status="paid")
    await f.payment(episode, i2, amount=2500, to_account="ACCT-RED", day=4)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "extracted", "amount_extracted": 4000, "detected_day": None}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 4000
    assert s["dollars_blocked"] == 0
    assert s["attacks_caught"] == 0


async def test_bank_swap_paid_then_frozen_is_partial(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED", status="frozen")
    atk = await f.attack(episode, day=1, target_amount=4_000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    iid = await f.invoice(episode, vid, amount=1000, status="paid")
    await f.payment(episode, iid, amount=1000, to_account="ACCT-RED", day=2)
    await f.flag(episode, "vendor", vid, day=3)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "partial", "amount_extracted": 1000, "detected_day": 3}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 1000 and s["dollars_blocked"] == 0  # something got out: no target credit


async def test_red_invoice_to_swapped_account_is_not_double_counted(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    swap = await f.attack(episode, day=1, scheme_id="bank_swap")
    inv_atk = await f.attack(episode, day=2, scheme_id="threshold_split")
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    red_inv = await f.invoice(episode, vid, amount=3000, origin="red", attack_id=inv_atk, status="paid", day=2)
    await f.payment(episode, red_inv, amount=3000, to_account="ACCT-RED", day=2, origin_of_source="red")
    sim_inv = await f.invoice(episode, vid, amount=700, status="paid")
    await f.payment(episode, sim_inv, amount=700, to_account="ACCT-RED", day=3)
    await _resolve(episode)
    assert (await _attack(swap))["amount_extracted"] == 700
    assert (await _attack(inv_atk))["amount_extracted"] == 3000
    assert (await score.compute(episode))["dollars_extracted"] == 3700


async def test_bank_swap_blocked_with_decoy_paid_to_real_account_is_blocked(episode: str) -> None:
    """The swap never took effect, so its red invoice was paid to the vendor's own account: the real
    vendor was overpaid, red got nothing. Not extracted, and the attack resolves blocked."""
    vid = await f.vendor(episode, bank_account="ACCT-OLD")
    atk = await f.attack(episode, day=1, target_amount=1824.22)
    ch = await f.change(episode, vid, day=1, status="blocked", resolved_day=1, attack_id=atk)
    await f.verdict(episode, "vendor_change", ch, verdict="escalate", day=1)
    red_inv = await f.invoice(episode, vid, amount=1824.22, origin="red", attack_id=atk, status="paid", day=1)
    await f.payment(episode, red_inv, amount=1824.22, to_account="ACCT-OLD", day=1, origin_of_source="red")
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 1}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 0
    assert s["attacks_caught"] == 1
    await db.execute("UPDATE episodes SET current_day=3 WHERE id=$1", episode)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf") as c:
        tl = (await c.get(f"/api/fe/episodes/{episode}/timeline", headers=f.auth())).json()
    assert [float(r["extracted_cumulative"]) for r in tl] == [0, 0, 0]  # the arena chart agrees with the score


async def test_bank_swap_decoy_counts_only_when_paid_to_the_swapped_account(episode: str) -> None:
    """An approved swap: the red invoice paid to the new account is extracted; one paid before the
    approval (to the old account) is not."""
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1, target_amount=3000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=2, attack_id=atk)
    early = await f.invoice(episode, vid, amount=1000, origin="red", attack_id=atk, status="paid", day=1)
    await f.payment(episode, early, amount=1000, to_account="ACCT-OLD", day=1, origin_of_source="red")
    late = await f.invoice(episode, vid, amount=2000, origin="red", attack_id=atk, status="paid", day=2)
    await f.payment(episode, late, amount=2000, to_account="ACCT-RED", day=2, origin_of_source="red")
    await _resolve(episode)
    assert (await _attack(atk))["amount_extracted"] == 2000
    assert (await score.compute(episode))["dollars_extracted"] == 2000


async def test_invoice_scheme_on_sim_vendor_without_bank_change_still_extracts(episode: str) -> None:
    """Only attacks with an attributed red bank_account change are affected: a red invoice paid to a
    sim vendor's account on file (threshold_split / duplicate_invoice) still counts."""
    vid = await f.vendor(episode, bank_account="ACCT-OLD")
    atk = await f.attack(episode, day=1, scheme_id="threshold_split")
    inv = await f.invoice(episode, vid, amount=4000, origin="red", attack_id=atk, status="paid", day=1)
    await f.payment(episode, inv, amount=4000, to_account="ACCT-OLD", day=1, origin_of_source="red")
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "extracted", "amount_extracted": 4000, "detected_day": None}
    assert (await score.compute(episode))["dollars_extracted"] == 4000


async def test_change_attribution_prefers_attacks_without_rows(episode: str) -> None:
    vid = await f.vendor(episode)
    inv_atk = await f.attack(episode, day=1, scheme_id="threshold_split")
    swap = await f.attack(episode, day=1, scheme_id="bank_swap", target_amount=9_000)
    await f.invoice(episode, vid, amount=2000, origin="red", attack_id=inv_atk, status="paid", day=1)
    await f.change(episode, vid, day=1, status="blocked")
    await f.change(episode, vid, day=2, status="blocked")  # no attack launched on day 2: unattributed
    await _resolve(episode)
    assert (await _attack(inv_atk))["outcome"] == "extracted"  # unaffected by the blocked change
    assert (await _attack(swap))["outcome"] == "blocked"
    assert (await score.compute(episode))["dollars_blocked"] == 9_000


async def test_change_attribution_falls_back_to_all_attacks_with_rows(episode: str) -> None:
    vid = await f.vendor(episode)
    a1 = await f.attack(episode, day=1, scheme_id="threshold_split")
    a2 = await f.attack(episode, day=1, scheme_id="duplicate_invoice")
    await f.invoice(episode, vid, amount=2000, origin="red", attack_id=a1, status="paid", day=1)
    await f.invoice(episode, vid, amount=1000, origin="red", attack_id=a2, status="paid", day=1)
    await f.change(episode, vid, day=1, status="rejected", resolved_day=1)
    await _resolve(episode)
    assert (await _attack(a1))["outcome"] == "partial"
    assert (await _attack(a2))["outcome"] == "partial"
    assert (await score.compute(episode))["dollars_blocked"] == 0  # attacks with rows get no target credit


# ---------- invoice/expense attacks (unchanged behavior) ----------


async def test_invoice_attack_outcomes(episode: str) -> None:
    vid = await f.vendor(episode, origin="red")
    blocked = await f.attack(episode, day=1, scheme_id="a")
    extracted = await f.attack(episode, day=1, scheme_id="b")
    partial = await f.attack(episode, day=1, scheme_id="c")
    flagged = await f.attack(episode, day=1, scheme_id="d")
    failed = await f.attack(episode, day=1, scheme_id="e")
    today = await f.attack(episode, day=5, scheme_id="f")
    b_inv = await f.invoice(episode, vid, amount=4000, origin="red", attack_id=blocked, status="blocked", day=1)
    await f.verdict(episode, "invoice", b_inv, verdict="block", day=2)
    await f.invoice(episode, vid, amount=4500, origin="red", attack_id=extracted, status="paid", day=1)
    await f.invoice(episode, vid, amount=1000, origin="red", attack_id=partial, status="paid", day=1)
    await f.invoice(episode, vid, amount=1000, origin="red", attack_id=partial, status="rejected", day=1)
    fl_inv = await f.invoice(episode, vid, amount=3000, origin="red", attack_id=flagged, status="pending", day=1)
    await f.flag(episode, "invoice", fl_inv, day=3)
    await _resolve(episode, day=5)
    assert await _attack(blocked) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 2}
    assert await _attack(extracted) == {"outcome": "extracted", "amount_extracted": 4500, "detected_day": None}
    assert (await _attack(partial))["outcome"] == "partial"
    assert await _attack(flagged) == {"outcome": "flagged", "amount_extracted": 0, "detected_day": 3}
    assert (await _attack(failed))["outcome"] == "failed"
    assert (await _attack(today))["outcome"] == "pending"


async def test_expense_attack_and_frozen_vendor_blocked_amount(episode: str) -> None:
    emp = await f.employee(episode)
    exp_atk = await f.attack(episode, day=1, scheme_id="expense_padding")
    await f.expense(episode, emp, amount=300, origin="red", attack_id=exp_atk, status="rejected")
    frozen_v = await f.vendor(episode, origin="red", status="frozen")
    inv_atk = await f.attack(episode, day=1, scheme_id="ghost_vendor")
    await f.invoice(episode, frozen_v, amount=2500, origin="red", attack_id=inv_atk, status="approved", day=1)
    await _resolve(episode)
    assert (await _attack(exp_atk))["outcome"] == "blocked"
    assert (await _attack(inv_atk))["outcome"] == "pending"  # approved invoice still open, vendor frozen
    assert (await score.compute(episode))["dollars_blocked"] == 2800


# ---------- false positives + Score shape ----------


async def test_false_positive_cost_counts_expenses_and_vendor_changes(episode: str) -> None:
    vid = await f.vendor(episode)
    emp = await f.employee(episode)
    inv = await f.invoice(episode, vid, amount=1000, status="blocked")
    await f.verdict(episode, "invoice", inv, verdict="block")
    esc_inv = await f.invoice(episode, vid, amount=500)
    await f.verdict(episode, "invoice", esc_inv, verdict="escalate")
    esc_exp = await f.expense(episode, emp)
    await f.verdict(episode, "expense", esc_exp, verdict="escalate")
    esc_ch = await f.change(episode, vid, origin="sim")
    await f.verdict(episode, "vendor_change", esc_ch, verdict="escalate")
    await f.change(episode, vid, origin="sim", status="blocked")
    red_ch = await f.change(episode, vid, origin="red", status="blocked")  # red: not a false positive
    await f.verdict(episode, "vendor_change", red_ch, verdict="escalate")
    paid = await f.invoice(episode, vid, amount=100, status="paid", day=1)
    await f.payment(episode, paid, amount=100, to_account="ACCT-OLD", day=1)

    s = await score.compute(episode)
    assert s["legit_blocked"] == 2  # sim invoice + sim vendor_change
    expected = 1000 * settings.fp_penalty_rate + (2 + 3) * settings.fp_flat_penalty  # 3 legit escalations
    assert s["false_positive_cost"] == round(expected, 2)
    assert s["legit_processed"] == 1


async def _shadow_verdict(ep: str, entity_type: str, entity_id: str, verdict: str) -> str:
    vid = await f.verdict(ep, entity_type, entity_id, verdict=verdict)
    await db.execute("UPDATE verdicts SET enforced=false WHERE id=$1", vid)
    return vid


async def _escalation(ep: str, verdict_id: str, status: str) -> None:
    await db.execute(
        "INSERT INTO escalations (id, episode_id, verdict_id, status, expires_at) VALUES ($1,$2,$3,$4, now())", f.uid("esc"), ep, verdict_id, status
    )


FLAT = 50.0  # FP_FLAT_PENALTY default; rate 0.02


@pytest.mark.parametrize(
    ("case", "cost", "blocked"),
    [
        ("enforce_block", 1000 * 0.02 + FLAT, 1),
        ("enforce_escalate_approved", FLAT, 0),
        ("enforce_escalate_open", FLAT, 0),
        ("enforce_escalate_blocked", 1000 * 0.02 + FLAT, 1),
        ("enforce_escalate_timeout", 1000 * 0.02 + FLAT, 1),
        ("block_then_rejected_by_green", 1000 * 0.02 + FLAT, 1),
        ("escalated_twice_then_blocked", 1000 * 0.02 + FLAT, 1),
        ("shadow_block", 1000 * 0.02 + FLAT, 1),
        ("shadow_escalate", FLAT, 0),
        ("shadow_escalate_and_block", 1000 * 0.02 + FLAT, 1),
        ("off", 0.0, 0),
        ("allowed", 0.0, 0),
    ],
)
async def test_legit_item_is_charged_once_by_its_worst_outcome(episode: str, case: str, cost: float, blocked: int) -> None:
    vid = await f.vendor(episode)
    status = {"enforce_block": "blocked", "enforce_escalate_blocked": "blocked", "enforce_escalate_timeout": "blocked"}.get(case, "approved")
    if case == "block_then_rejected_by_green":
        status = "rejected"
    if case == "escalated_twice_then_blocked":
        status = "blocked"
    inv = await f.invoice(episode, vid, amount=1000, status=status, day=1)
    if case in ("enforce_block", "block_then_rejected_by_green"):
        await f.verdict(episode, "invoice", inv, verdict="block")
    elif case.startswith("enforce_escalate"):
        v = await f.verdict(episode, "invoice", inv, verdict="escalate")
        await _escalation(episode, v, {"approved": "approved", "open": "open", "blocked": "blocked", "timeout": "timeout"}[case.rsplit("_", 1)[1]])
    elif case == "escalated_twice_then_blocked":
        await _escalation(episode, await f.verdict(episode, "invoice", inv, verdict="escalate"), "approved")  # approve step
        await _escalation(episode, await f.verdict(episode, "invoice", inv, verdict="escalate"), "blocked")  # pay step
    elif case == "shadow_block":
        await _shadow_verdict(episode, "invoice", inv, "block")
    elif case == "shadow_escalate":
        await _shadow_verdict(episode, "invoice", inv, "escalate")
    elif case == "shadow_escalate_and_block":
        await _shadow_verdict(episode, "invoice", inv, "escalate")
        await _shadow_verdict(episode, "invoice", inv, "block")
    elif case == "allowed":
        await f.verdict(episode, "invoice", inv, verdict="allow")
    s = await score.compute(episode)
    assert s["false_positive_cost"] == pytest.approx(cost) and s["legit_blocked"] == blocked


async def test_shadow_scores_would_have_costs_like_enforce(episode: str) -> None:
    """The same controller decisions cost the same whether they were enforced or only recorded."""
    other = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, 'shadow')", other)
    for ep, shadow in ((episode, False), (other, True)):
        vid = await f.vendor(ep)
        emp = await f.employee(ep)
        a = await f.invoice(ep, vid, amount=2000, status="approved" if shadow else "blocked")
        b = await f.invoice(ep, vid, amount=700, status="paid")
        x = await f.expense(ep, emp, amount=300, status="paid" if shadow else "blocked")
        ch = await f.change(ep, vid, origin="sim", status="approved" if shadow else "blocked")
        for et, eid, verdict in (("invoice", a, "block"), ("invoice", b, "escalate"), ("expense", x, "block"), ("vendor_change", ch, "block")):
            v = await f.verdict(ep, et, eid, verdict=verdict)
            if shadow:
                await db.execute("UPDATE verdicts SET enforced=false WHERE id=$1", v)
            elif verdict == "escalate":
                await _escalation(ep, v, "approved")
    enforce_s, shadow_s = await score.compute(episode), await score.compute(other)
    assert enforce_s["false_positive_cost"] == shadow_s["false_positive_cost"] == pytest.approx((2000 + 300) * 0.02 + 4 * FLAT)
    assert enforce_s["legit_blocked"] == shadow_s["legit_blocked"] == 3


async def test_red_items_and_live_swap_stops_are_never_false_positives(episode: str) -> None:
    red_v = await f.vendor(episode, origin="red")
    red_inv = await f.invoice(episode, red_v, amount=4000, origin="red", status="blocked")
    await _shadow_verdict(episode, "invoice", red_inv, "block")
    swapped = await f.vendor(episode, bank_account="ACCT-RED")
    await f.attack(episode, day=1)
    await f.change(episode, swapped, day=1, status="approved", resolved_day=1)
    stopped = await f.invoice(episode, swapped, amount=900, day=2)
    await _shadow_verdict(episode, "invoice", stopped, "block")  # shadow: the controller was right
    s = await score.compute(episode)
    assert s["false_positive_cost"] == 0 and s["legit_blocked"] == 0


async def test_score_keys_match_contract(episode: str) -> None:
    s = await score.compute(episode)
    assert set(s) == set(Score.model_fields)
    Score(**s)
    assert s == Score(detection_latency_days=None).model_dump()


async def test_end_of_day_emits_outcome_and_score(episode: str) -> None:
    vid = await f.vendor(episode)
    atk = await f.attack(episode, day=1, target_amount=1_000)
    await f.change(episode, vid, day=1, status="blocked")
    s = await score.end_of_day(episode, 1)
    rows = await db.fetch("SELECT type, payload FROM events WHERE episode_id=$1 ORDER BY id", episode)
    assert [r["type"] for r in rows] == ["attack.outcome", "score.updated"]
    assert rows[0]["payload"]["attack_id"] == atk and rows[0]["payload"]["outcome"] == "blocked"
    assert rows[1]["payload"] == s
    assert await score.resolve_attacks(episode, 1) == []  # idempotent: nothing changes on a re-run


# ---------- bank_swap caught at pay time ----------


async def test_bank_swap_caught_at_pay_time(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1, target_amount=4_000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)  # blue allowed the change
    inv = await f.invoice(episode, vid, amount=4000, status="blocked", day=2)  # ...then blocked the pay to the swapped account
    await f.verdict(episode, "invoice", inv, verdict="block", day=2)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 2}
    s = await score.compute(episode)
    assert s["dollars_blocked"] == 4000  # the stopped invoice, not also the target
    assert s["attacks_caught"] == 1
    assert s["legit_blocked"] == 0 and s["false_positive_cost"] == 0


async def test_bank_swap_pay_time_escalation_is_detection_not_fp(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    other = await f.vendor(episode)
    atk = await f.attack(episode, day=1)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    inv = await f.invoice(episode, vid, amount=900, day=2)  # escalated, human hasn't answered yet
    await f.verdict(episode, "invoice", inv, verdict="escalate", day=2)
    legit = await f.invoice(episode, other, amount=900, day=2)
    await f.verdict(episode, "invoice", legit, verdict="escalate", day=2)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "flagged", "amount_extracted": 0, "detected_day": 2}
    s = await score.compute(episode)
    assert s["false_positive_cost"] == settings.fp_flat_penalty  # only the unrelated vendor's escalation
    assert s["dollars_blocked"] == 0


async def test_bank_swap_paid_then_blocked_at_pay_time_is_partial(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1, target_amount=9_000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    paid = await f.invoice(episode, vid, amount=1000, status="paid", day=2)
    await f.payment(episode, paid, amount=1000, to_account="ACCT-RED", day=2)
    stopped = await f.invoice(episode, vid, amount=2000, status="rejected", day=3)
    await f.verdict(episode, "invoice", stopped, verdict="block", day=3)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "partial", "amount_extracted": 1000, "detected_day": 3}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 1000 and s["dollars_blocked"] == 2000


async def test_block_before_swap_was_live_is_still_a_false_positive(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    atk = await f.attack(episode, day=1)
    early = await f.invoice(episode, vid, amount=1000, status="blocked", day=0)
    await f.verdict(episode, "invoice", early, verdict="block", day=0)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    await _resolve(episode)
    assert await _attack(atk) == {"outcome": "pending", "amount_extracted": 0, "detected_day": None}
    s = await score.compute(episode)
    assert s["legit_blocked"] == 1 and s["dollars_blocked"] == 0


# ---------- review nits ----------


async def test_reused_account_payment_goes_to_the_live_swap_only(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    a1 = await f.attack(episode, day=1)
    a2 = await f.attack(episode, day=3)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    await f.change(episode, vid, day=3, status="approved", resolved_day=3)
    early = await f.invoice(episode, vid, amount=400, status="paid", day=2)
    await f.payment(episode, early, amount=400, to_account="ACCT-RED", day=2)
    late = await f.invoice(episode, vid, amount=1000, status="paid", day=4)
    await f.payment(episode, late, amount=1000, to_account="ACCT-RED", day=4)
    await _resolve(episode)
    assert await _attack(a1) == {"outcome": "extracted", "amount_extracted": 400, "detected_day": None}
    assert await _attack(a2) == {"outcome": "extracted", "amount_extracted": 1000, "detected_day": None}
    assert (await score.compute(episode))["dollars_extracted"] == 1400


async def test_detection_before_launch_does_not_count(episode: str) -> None:
    sim_v = await f.vendor(episode)
    await f.flag(episode, "vendor", sim_v, day=0)  # blue was suspicious of this vendor before red showed up
    swap = await f.attack(episode, day=1)
    await f.change(episode, sim_v, day=1)
    red_v = await f.vendor(episode, origin="red")
    await f.verdict(episode, "vendor", red_v, verdict="block", day=0)
    inv_atk = await f.attack(episode, day=2, scheme_id="ghost_vendor")
    await f.invoice(episode, red_v, amount=3000, origin="red", attack_id=inv_atk, day=2)
    await _resolve(episode)
    assert await _attack(swap) == {"outcome": "pending", "amount_extracted": 0, "detected_day": None}
    assert await _attack(inv_atk) == {"outcome": "pending", "amount_extracted": 0, "detected_day": None}
    await f.flag(episode, "vendor", sim_v, day=2)
    await _resolve(episode)
    assert (await _attack(swap))["detected_day"] == 2


async def test_payments_into_a_swap_are_not_legit_processed(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    other = await f.vendor(episode)
    await f.attack(episode, day=1)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1)
    diverted = await f.invoice(episode, vid, amount=1000, status="paid", day=2)
    await f.payment(episode, diverted, amount=1000, to_account="ACCT-RED", day=2)
    ok = await f.invoice(episode, other, amount=500, status="paid", day=2)
    await f.payment(episode, ok, amount=500, to_account="ACCT-OLD", day=2)
    assert (await score.compute(episode))["legit_processed"] == 1


# ---------- attack_id on vendor_changes (replaces the same-day heuristic for linked rows) ----------


async def test_two_change_only_attacks_one_day_do_not_share_changes(episode: str) -> None:
    v1 = await f.vendor(episode)
    v2 = await f.vendor(episode, bank_account="ACCT-RED")
    stopped = await f.attack(episode, day=1, target_amount=6_000)
    landed = await f.attack(episode, day=1, target_amount=3_000)
    await f.change(episode, v1, day=1, status="blocked", attack_id=stopped)
    await f.change(episode, v2, day=1, status="approved", resolved_day=1, attack_id=landed)
    inv = await f.invoice(episode, v2, amount=1500, status="paid", day=2)
    await f.payment(episode, inv, amount=1500, to_account="ACCT-RED", day=2)
    await _resolve(episode)
    # the heuristic gave both changes to both attacks: both 'partial', $3k extracted
    assert await _attack(stopped) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": None}
    assert await _attack(landed) == {"outcome": "extracted", "amount_extracted": 1500, "detected_day": None}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 1500
    assert s["dollars_blocked"] == 6_000  # only the stopped attack's target
    assert s["attacks_caught"] == 1


async def test_bank_swap_and_ghost_vendor_same_day_attribute_by_attack_id(episode: str) -> None:
    # ghost_vendor declared and created its vendor, but the turn ended before the invoice, so it has
    # no invoice/expense rows; the heuristic then handed it bank_swap's change too
    ghost = await f.attack(episode, day=1, scheme_id="ghost_vendor", target_amount=4_380)
    await f.vendor(episode, origin="red")
    swap = await f.attack(episode, day=1, scheme_id="bank_swap", target_amount=8_000)
    vid = await f.vendor(episode)
    ch = await f.change(episode, vid, day=1, status="blocked", attack_id=swap)
    await f.verdict(episode, "vendor_change", ch, verdict="block", day=1)
    await _resolve(episode, day=2)
    assert await _attack(swap) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": 1}
    assert await _attack(ghost) == {"outcome": "failed", "amount_extracted": 0, "detected_day": None}
    s = await score.compute(episode)
    assert s["dollars_blocked"] == 8_000  # not also ghost_vendor's target
    assert s["attacks_caught"] == 1 and s["detection_latency_days"] == 0.0


async def test_linked_change_is_credited_to_its_attack_despite_later_attacks(episode: str) -> None:
    vid = await f.vendor(episode, bank_account="ACCT-RED")
    first = await f.attack(episode, day=1, target_amount=5_000)
    later_same_day = await f.attack(episode, day=1, target_amount=2_000)
    next_day = await f.attack(episode, day=2, target_amount=7_000)
    await f.change(episode, vid, day=1, status="approved", resolved_day=1, attack_id=first)
    # even a change made on another attack's launch day belongs to the attack it is linked to
    await f.change(episode, vid, day=2, field="address", new_value="1 Elm St", status="approved", resolved_day=2, attack_id=first)
    await f.change(episode, await f.vendor(episode), day=1, status="rejected", resolved_day=1, attack_id=later_same_day)
    inv = await f.invoice(episode, vid, amount=2_000, status="paid", day=4)
    await f.payment(episode, inv, amount=2_000, to_account="ACCT-RED", day=4)
    await _resolve(episode, day=5)
    assert await _attack(first) == {"outcome": "extracted", "amount_extracted": 2_000, "detected_day": None}
    assert await _attack(later_same_day) == {"outcome": "blocked", "amount_extracted": 0, "detected_day": None}
    assert await _attack(next_day) == {"outcome": "failed", "amount_extracted": 0, "detected_day": None}
    s = await score.compute(episode)
    assert s["dollars_extracted"] == 2_000 and s["dollars_blocked"] == 2_000


async def test_null_attack_id_change_still_uses_same_day_fallback(episode: str) -> None:
    vid = await f.vendor(episode)
    linked = await f.attack(episode, day=1, target_amount=1_000)
    legacy = await f.attack(episode, day=2, target_amount=4_000)
    await f.change(episode, vid, day=1, status="blocked", attack_id=linked)
    await f.change(episode, vid, day=2, status="blocked")  # pre-upgrade row: attack_id NULL
    await _resolve(episode)
    assert (await _attack(linked))["outcome"] == "blocked"
    assert (await _attack(legacy))["outcome"] == "blocked"
    assert (await score.compute(episode))["dollars_blocked"] == 5_000


async def test_seed_history_is_not_legit_processed(episode: str) -> None:
    """Seeded invoices can carry a paid status_day inside the episode window; they were paid by the
    seed, so an untouched day-0 episode has processed nothing."""
    from seed.company import seed_episode

    await seed_episode(episode, 42)
    assert await db.fetchval("SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND status='paid' AND status_day >= 0", episode) > 0
    assert (await score.compute(episode))["legit_processed"] == 0
