import json

import httpx
import pytest
import respx

from agentkit.invocation import SOURCE_STREAM, Invocation, bind_invocation
from audit import tools
from audit.crs import BASE_URL, IDENTITY_PATH, PERSONAS, CRSClient, parse_identity
from audit.evidence import model_view
from gate.rules import evaluate

from .audit_helpers import FakeLedger, bound_session, turn


def delivered(codes=(), *, status="DELIVERED", search="CLEAR"):
    return {"addOnProducts": [{"status": status, "idManagerVerification": {"searchStatus": search, "messages": [{"code": c} for c in codes]}}]}


@pytest.mark.parametrize(
    "body,status",
    [
        (delivered(), "verified"),
        (delivered(["2201"], search="HIT"), "mismatch"),
        (delivered(["2202"]), "mismatch"),
        (delivered(["2301"]), "mismatch"),
        (delivered(["2101"]), "review"),
        (delivered(["2401"]), "review"),
        (delivered(["2401", "2201"]), "review"),
        (delivered(["NEW_CODE"]), "unknown"),
        (delivered(status="NOT_AUTHORIZED"), "unknown"),
        (delivered(search="UNAVAILABLE"), "unknown"),
        # Sponsor note (package v1.1.2): "messages: empty = verified" — observed P01 sandbox shape
        # is DELIVERED + HIT + zero messages, and must parse as verified, not unknown.
        (delivered(search="HIT"), "verified"),
        ({}, "unknown"),
        ({"addOnProducts": [{"status": "DELIVERED", "idManagerVerification": {"searchStatus": "CLEAR"}}]}, "unknown"),
        ({"addOnProducts": [delivered()["addOnProducts"][0]] * 2}, "unknown"),
        ({"errorMessages": ["private"], **delivered()}, "unknown"),
    ],
)
def test_delivered_evidence_only(body, status):
    assert parse_identity(body).status == status


@respx.mock
async def test_login_reused_and_exact_approved_body_not_persona_expectation():
    login = respx.post(f"{BASE_URL}/users/login").respond(200, json={"token": "test-jwt"})
    check = respx.post(f"{BASE_URL}{IDENTITY_PATH}").respond(200, json=delivered())
    client = CRSClient("sandbox-user", "dummy-password")
    for persona in ("P01", "P12"):
        body = PERSONAS[persona]
        assert (await client.verify(persona, f"{body['firstName']} {body['lastName']}", dry_run=False)).status == "verified"
        assert json.loads(check.calls[-1].request.content) == body
        assert check.calls[-1].request.headers["Authorization"] == "Bearer test-jwt"
    assert login.call_count == 1 and check.call_count == 2


@respx.mock
async def test_no_network_for_dry_run_missing_credentials_unknown_or_wrong_profile():
    for client, persona, name, dry in [
        (CRSClient("user", "password"), "P01", "MARGARET OKAFOR", True),
        (CRSClient(), "P01", "MARGARET OKAFOR", False),
        (CRSClient("user", "password"), "arbitrary", "Random Person", False),
        (CRSClient("user", "password"), "P01", "Random Person", False),
    ]:
        assert (await client.verify(persona, name, dry_run=dry)).status == "unknown"
    assert not respx.calls


@pytest.mark.parametrize("failure", ["login_rejected", "login_malformed", "timeout", "expired", "rate_limit", "redirect"])
@pytest.mark.respx(assert_all_called=False)
async def test_errors_neutral_no_login_retry(failure, respx_mock):
    login = respx_mock.post(f"{BASE_URL}/users/login").respond(
        401 if failure == "login_rejected" else 200, json=[] if failure == "login_malformed" else {"token": "test-jwt"}
    )
    check = respx_mock.post(f"{BASE_URL}{IDENTITY_PATH}")
    if failure == "timeout":
        check.side_effect = httpx.ReadTimeout("private provider response")
    else:
        check.respond({"expired": 401, "rate_limit": 429, "redirect": 302}.get(failure, 200), json={"private": "not evidence"})
    client = CRSClient("user", "password")
    for _ in range(2):
        assert (await client.verify("P01", "MARGARET OKAFOR", dry_run=False)).status == "unknown"
    assert login.call_count == 1
    if failure in {"login_rejected", "login_malformed"}:
        assert not check.called


@pytest.mark.parametrize("codes,held", [([], False), (["2201"], True), (["2401"], False), (["unknown"], False)])
@respx.mock
async def test_profile_to_crs_finding_receipt_then_expense_gate(monkeypatch, gate_request, codes, held):
    respx.post(f"{BASE_URL}/users/login").respond(200, json={"token": "test-jwt"})
    check = respx.post(f"{BASE_URL}{IDENTITY_PATH}").respond(200, json=delivered(codes))
    monkeypatch.setattr(tools, "crs_client", lambda: CRSClient("user", "password"))
    employee = {"id": "emp", "name": "MARGARET OKAFOR", "status": "active", "start_day": 5, "hr_record": True, "bank_account": "employee-only"}
    ledger = FakeLedger(employees=[employee])

    async def profile(area, path):
        assert (area, path) == ("blue", "crs/employees/emp")
        return {"persona_id": "P01"}

    ledger.get_extension = profile

    # Unit-supplied SDK metadata, not evidence of an authenticated live session.
    async def invoke(name, invocation_id, **arguments):
        token = tools.INVOCATION.set(invocation_id)
        try:
            with bind_invocation(Invocation(invocation_id, name, source=SOURCE_STREAM)):
                return json.loads(await getattr(tools, name)(**arguments))
        finally:
            tools.INVOCATION.reset(token)

    async with bound_session(ledger, dry_run=False) as (session, emitter):
        first = await invoke("crs_identity_check", "verified-check")
        assert await invoke("crs_identity_check", "verified-recheck") == first and check.call_count == 1
        assert len(session.snapshot.findings) == int(held)
        if held:
            finding = session.snapshot.findings[0]
            assert (await invoke("raise_flag", "verified-flag", finding_id=finding.id))["state"] == "confirmed"
            assert session.effects[-1].tool_use_id == ledger.writes[-1][2] == "verified-flag"
            assert not tools.freeze_authorized([finding])
        projected = json.dumps(model_view(session.snapshot)) + json.dumps(emitter.calls) + json.dumps(emitter.results)
        assert all(private not in projected for private in ("MARGARET", "666701001", "WILLOW", "test-jwt", "dummy-password", "P01"))
        flags = [{"entity_type": args[0], "entity_id": args[1], "severity": args[2], "reason": args[3]} for kind, args, _ in ledger.writes if kind == "flag"]
        req = gate_request(
            action="expenses.pay",
            entity_type="expense",
            entity_id="exp",
            context={
                "employee": employee,
                "expense": {"id": "exp", "employee_id": "emp", "amount": 1200},
                "vendors_sharing_bank_account": [],
                "flags": flags,
            },
        )
        assert any(hit.id == "already_flagged_high" for hit in evaluate(req)) == held


@respx.mock
async def test_dry_run_audit_with_credentials_still_neutral_and_idempotent(runtime, monkeypatch):
    monkeypatch.setattr(tools, "crs_client", lambda: CRSClient("user", "password"))
    ledger = FakeLedger(employees=[{"id": "emp", "name": "MARGARET OKAFOR", "status": "active", "start_day": 5, "hr_record": True, "bank_account": "employee"}])
    agent, _, emitter = runtime(ledger)
    response = await agent.run_turn(turn())
    assert response.ok and await agent.run_turn(turn()) == response
    assert agent.outcome("ep", 5).flags_raised == 0 and not respx.calls
    assert "CRS unknown/step-up: 1" in ledger.writes[-1][1][1]
    assert len(emitter.calls) == len(emitter.results)
