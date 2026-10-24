"""Owner: Dev Al. Pattern: mock the Ledger API with respx and assert the scheme's calls."""

import json

import httpx
import respx

from agentkit import AgentSettings, LedgerClient
from schemes import SCHEMES
from schemes.ghost_vendor import GhostVendor

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")


def test_catalog_shape():
    for s in SCHEMES.values():
        c = s.catalog()
        assert c.id and c.display_name and c.story.endswith(".")


@respx.mock
async def test_ghost_vendor_execute_creates_vendor_and_invoice():
    respx.post("http://bf/api/vendors").mock(return_value=httpx.Response(201, json={"id": "ven_x", "name": "Acme Office Supply LLC"}))
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await GhostVendor().plan(L, {"amount": 4200})
        out = await GhostVendor().execute(L, plan)
    assert "4,200.00" in out
    body = json.loads(inv.calls[0].request.content)
    assert body["vendor_id"] == "ven_x" and body["amount"] == 4200
    assert inv.calls[0].request.headers["X-Agent"] == "red"
