"""CRS_LIVE acceptance switch: the keyless audit calls the sandbox only when explicitly armed."""

import json
import os

import pytest
import respx

from agentkit.invocation import SOURCE_STREAM, Invocation, bind_invocation
from audit import tools
from audit.crs import BASE_URL, IDENTITY_PATH, PERSONAS, CRSClient, crs_live

from .audit_helpers import FakeLedger, bound_session


def delivered(codes=(), *, status="DELIVERED", search="CLEAR"):
    return {"addOnProducts": [{"status": status, "idManagerVerification": {"searchStatus": search, "messages": [{"code": c} for c in codes]}}]}


def env_client():
    # Bypass the lru_cached singleton so each test reads its own monkeypatched environment.
    return CRSClient(os.environ.get("CRS_USERNAME", ""), os.environ.get("CRS_PASSWORD", ""))


@pytest.fixture
def employee():
    return {"id": "emp", "name": "margaret okafor", "status": "active", "start_day": 5, "hr_record": True, "bank_account": "employee-only"}


@pytest.fixture
def ledger(employee, monkeypatch):
    monkeypatch.setattr(tools, "crs_client", env_client)
    ledger = FakeLedger(employees=[employee])

    async def profile(area, path):
        assert (area, path) == ("blue", "crs/employees/emp")
        return {"persona_id": "P01"}

    ledger.get_extension = profile
    return ledger


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("CRS_USERNAME", "sandbox-user")
    monkeypatch.setenv("CRS_PASSWORD", "dummy-password")


async def invoke(name, invocation_id, **arguments):
    # Unit-supplied SDK metadata, not evidence of an authenticated live session.
    token = tools.INVOCATION.set(invocation_id)
    try:
        with bind_invocation(Invocation(invocation_id, name, source=SOURCE_STREAM)):
            return json.loads(await getattr(tools, name)(**arguments))
    finally:
        tools.INVOCATION.reset(token)


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
def test_crs_live_parsing_on(monkeypatch, value):
    monkeypatch.setenv("CRS_LIVE", value)
    assert crs_live() is True


@pytest.mark.parametrize("value", ["", "false", "0", "garbage"])
def test_crs_live_parsing_off(monkeypatch, value):
    monkeypatch.setenv("CRS_LIVE", value)
    assert crs_live() is False


def test_crs_live_default_off(monkeypatch):
    monkeypatch.delenv("CRS_LIVE", raising=False)
    assert crs_live() is False


@respx.mock
async def test_default_off_dry_session_credentials_present_no_provider_calls(ledger, credentials, monkeypatch):
    monkeypatch.delenv("CRS_LIVE", raising=False)
    async with bound_session(ledger, dry_run=True) as (session, _emitter):
        assert await invoke("crs_identity_check", "live-off") == {"verified": 0, "mismatch": 0, "review": 0, "unknown": 1}
    assert not respx.calls


@respx.mock
async def test_crs_live_true_dry_session_verified_single_login_and_check(ledger, credentials, monkeypatch):
    monkeypatch.setenv("CRS_LIVE", "true")
    login = respx.post(f"{BASE_URL}/users/login").respond(200, json={"token": "test-jwt"})
    check = respx.post(f"{BASE_URL}{IDENTITY_PATH}").respond(200, json=delivered())
    async with bound_session(ledger, dry_run=True) as (session, _emitter):
        assert await invoke("crs_identity_check", "live-on") == {"verified": 1, "mismatch": 0, "review": 0, "unknown": 0}
        assert not session.snapshot.findings
    assert login.call_count == 1 and check.call_count == 1
    # Case-insensitive persona name matching: the employee name is lowercase.
    assert json.loads(check.calls[-1].request.content) == PERSONAS["P01"]


@respx.mock
async def test_crs_live_true_without_credentials_stays_unknown(ledger, monkeypatch):
    monkeypatch.setenv("CRS_LIVE", "true")
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    async with bound_session(ledger, dry_run=True) as (session, _emitter):
        assert await invoke("crs_identity_check", "live-nocreds") == {"verified": 0, "mismatch": 0, "review": 0, "unknown": 1}
    assert not respx.calls


@respx.mock
async def test_crs_live_true_mismatch_raises_high_severity_finding(ledger, credentials, monkeypatch):
    monkeypatch.setenv("CRS_LIVE", "true")
    respx.post(f"{BASE_URL}/users/login").respond(200, json={"token": "test-jwt"})
    respx.post(f"{BASE_URL}{IDENTITY_PATH}").respond(200, json=delivered(["2201"], search="HIT"))
    async with bound_session(ledger, dry_run=True) as (session, _emitter):
        assert await invoke("crs_identity_check", "live-mismatch") == {"verified": 0, "mismatch": 1, "review": 0, "unknown": 0}
        findings = [f for f in session.snapshot.findings if f.code == "crs_employee_identity_mismatch"]
        assert len(findings) == 1 and findings[0].severity == "high" and findings[0].entity_id == "emp"


@respx.mock
async def test_crs_live_set_non_dry_session_calls_as_before(ledger, credentials, monkeypatch):
    monkeypatch.setenv("CRS_LIVE", "true")
    respx.post(f"{BASE_URL}/users/login").respond(200, json={"token": "test-jwt"})
    check = respx.post(f"{BASE_URL}{IDENTITY_PATH}").respond(200, json=delivered())
    async with bound_session(ledger, dry_run=False) as (session, _emitter):
        assert await invoke("crs_identity_check", "live-nondry") == {"verified": 1, "mismatch": 0, "review": 0, "unknown": 0}
    assert check.call_count == 1


@respx.mock
async def test_crs_live_true_provider_failure_stays_unknown_no_retry(ledger, credentials, monkeypatch):
    monkeypatch.setenv("CRS_LIVE", "true")
    login = respx.post(f"{BASE_URL}/users/login").respond(401, json={"private": "rejected"})
    check = respx.post(f"{BASE_URL}{IDENTITY_PATH}")
    async with bound_session(ledger, dry_run=True) as (session, _emitter):
        first = await invoke("crs_identity_check", "live-fail")
        assert first == {"verified": 0, "mismatch": 0, "review": 0, "unknown": 1}
        assert await invoke("crs_identity_check", "live-fail-again") == first
    assert login.call_count == 1 and not check.called
