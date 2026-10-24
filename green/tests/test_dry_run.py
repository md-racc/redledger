"""Owner: Dev M. Dry-run AP clerk against a fake Ledger API."""

import httpx
import respx

from agent import GreenAgent
from agentkit import AgentSettings, LedgerClient, TurnRequest
from agentkit.tools import ctx

S = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)


@respx.mock
async def test_dry_run_pays_small_invoice_and_skips_blocked():
    respx.get("http://bf/api/vendor_changes").mock(return_value=httpx.Response(200, json=[]))
    respx.get("http://bf/api/purchase_orders").mock(return_value=httpx.Response(200, json=[{"id": "po_1"}]))
    respx.get("http://bf/api/invoices", params={"status": "pending"}).mock(
        return_value=httpx.Response(200, json=[{"id": "inv_1", "amount": 1200, "po_id": "po_1"}, {"id": "inv_2", "amount": 4900, "po_id": None}])
    )
    respx.post("http://bf/api/invoices/inv_1/match").mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.post("http://bf/api/invoices/inv_2/approve").mock(
        return_value=httpx.Response(403, json={"verdict": "block", "reason": "vendor_age_lt_7d", "verdict_id": "vd_1"})
    )
    respx.get("http://bf/api/invoices", params={"status": "matched"}).mock(return_value=httpx.Response(200, json=[{"id": "inv_1", "amount": 1200}]))
    respx.get("http://bf/api/invoices", params={"status": "approved"}).mock(return_value=httpx.Response(200, json=[]))
    pay = respx.post("http://bf/api/invoices/inv_1/pay").mock(return_value=httpx.Response(200, json={"id": "pay_1"}))
    respx.get("http://bf/api/expenses").mock(return_value=httpx.Response(200, json=[]))
    respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={"accepted": 0}))

    agent = GreenAgent(S)
    req = TurnRequest(episode_id="ep", day=1, controller_mode="enforce")
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        toks = ctx.bind(L, None, req)
        try:
            summary = await agent.dry_run_turn(req)
        finally:
            ctx.unbind(toks)
    assert pay.called
    assert "blocked 1" in summary
