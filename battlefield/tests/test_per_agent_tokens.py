"""Per-agent tokens (contracts/agent-service.md "Tokens"). Owner: Dev Ad.

Unit tests need no DB; the impersonation-audit test uses the `pg` fixture. The renderer tests run
deploy/render-env.sh in a subprocess with a clean environment, like test_crs_runtime.py.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import db
from app.auth import Caller, bearer, caller
from app.config import settings
from app.gate import gatekeeper
from app.orchestrator import agents
from tests.factories import AGENT_TOKEN, OPERATOR_TOKEN, auth

ROOT = Path(__file__).resolve().parents[2]
OWN = {"red": "tok-red", "green": "tok-green", "blue": "tok-blue"}

app = FastAPI()


@app.get("/read")
def read(c: Caller = Depends(caller)) -> dict:
    return {"agent": c.agent}


@app.get("/operator_only", dependencies=[Depends(bearer)])
def operator_only() -> dict:
    return {"ok": True}


client = TestClient(app)


@pytest.fixture
def per_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    for a, t in OWN.items():
        monkeypatch.setattr(settings, f"agent_token_{a}", t)


@pytest.mark.usefixtures("per_agent")
def test_each_agent_authenticates_only_with_its_own_token() -> None:
    for a, t in OWN.items():
        assert client.get("/read", headers=auth(a, token=t)).json() == {"agent": a}
    # another agent's token, the shared fallback token, or the operator token never authenticates an X-Agent
    assert client.get("/read", headers=auth("green", token=OWN["red"])).status_code == 401
    assert client.get("/read", headers=auth("blue", token=OWN["green"])).status_code == 401
    assert client.get("/read", headers=auth("red", token=AGENT_TOKEN)).status_code == 401
    assert client.get("/read", headers=auth("red", token=OPERATOR_TOKEN)).status_code == 401
    # an agent token without X-Agent is not the operator
    assert client.get("/read", headers=auth(token=OWN["red"])).status_code == 401
    assert client.get("/operator_only", headers=auth(token=OWN["blue"])).status_code == 401
    # operator unchanged
    assert client.get("/read", headers=auth()).json() == {"agent": None}


@pytest.mark.usefixtures("per_agent")
def test_unknown_x_agent_is_400_only_with_a_valid_agent_token() -> None:
    r = client.get("/read", headers=auth("purple", token=OWN["red"]))
    assert r.status_code == 400 and "unknown X-Agent" in r.json()["detail"]
    assert client.get("/read", headers=auth("purple", token="garbage")).status_code == 401
    assert client.get("/read", headers=auth("purple", token=OPERATOR_TOKEN)).status_code == 401


def test_single_token_mode_still_works_and_warns() -> None:
    # conftest leaves the per-agent tokens unset: every agent falls back to the shared token
    for a in OWN:
        assert client.get("/read", headers=auth(a)).json() == {"agent": a}
    s = settings.model_copy(update={"agent_token_red": None, "agent_token_green": None, "agent_token_blue": None})
    warnings = s.token_warnings()
    assert any("per-agent separation off" in w and "red/green/blue" in w for w in warnings)
    assert all(AGENT_TOKEN not in w and OPERATOR_TOKEN not in w for w in warnings)


def test_partial_fallback_names_only_the_missing_agents() -> None:
    s = settings.model_copy(update={"agent_token_red": "a", "agent_token_green": "b", "agent_token_blue": None})
    warnings = s.token_warnings()
    assert any(w.startswith("AGENT_TOKEN_BLUE unset; blue use") for w in warnings)
    assert not any("AGENT_TOKEN_RED unset" in w for w in warnings)


def test_equal_tokens_warn_naming_the_pair_never_the_value() -> None:
    s = settings.model_copy(update={"agent_token_red": "same", "agent_token_green": "same", "agent_token_blue": "c", "operator_token": "c"})
    warnings = s.token_warnings()
    assert "AGENT_TOKEN_RED equals AGENT_TOKEN_GREEN; separation between them is off" in warnings
    assert "AGENT_TOKEN_BLUE equals OPERATOR_TOKEN; separation between them is off" in warnings
    assert all("same" not in w.split(";")[0].replace("AGENT_TOKEN_", "") for w in warnings)
    clean = settings.model_copy(update={"agent_token_red": "a", "agent_token_green": "b", "agent_token_blue": "c", "operator_token": "o"})
    assert clean.token_warnings() == []


@pytest.mark.usefixtures("per_agent")
def test_battlefield_calls_each_agent_with_its_own_token() -> None:
    for a, t in OWN.items():
        assert agents._headers(a) == {"Authorization": f"Bearer {t}"}


@pytest.mark.usefixtures("per_agent")
async def test_turn_reflect_audit_schemes_and_gate_carry_the_right_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200

        def json(self) -> Any:
            return (
                {"verdict": "allow", "reason": "", "rules_fired": []}
                if self._url.endswith("/gate")
                else ([] if self._url.endswith("/schemes") else {"ok": True})
            )

        def raise_for_status(self) -> None:
            return None

        def __init__(self, url: str) -> None:
            self._url = url

    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
            sent.append((url, (headers or {})["Authorization"]))
            return FakeResponse(url)

        async def get(self, url: str, headers: dict | None = None) -> FakeResponse:
            sent.append((url, (headers or {})["Authorization"]))
            return FakeResponse(url)

    monkeypatch.setattr(agents.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gatekeeper.httpx, "AsyncClient", FakeClient)
    await agents.turn("red", "ep_1", 0, "enforce")
    await agents.turn("green", "ep_1", 0, "enforce")
    await agents.audit("ep_1", 0)
    await agents.reflect("blue", {"episode_id": "ep_1"})
    await agents.schemes()
    c = Caller(agent="green", episode_id="ep_1", day=0, tool_use_id="tu_1")
    await gatekeeper._ask_blue(c, "enforce", "invoices.pay", "invoice", "inv_1", 10.0, {}, {})
    got = {(u.rsplit("/", 1)[-1], u.split("/")[2]): h for u, h in sent}
    assert got[("turn", settings.red_url.split("/")[2])] == "Bearer tok-red"
    assert got[("turn", settings.green_url.split("/")[2])] == "Bearer tok-green"
    assert got[("audit", settings.blue_url.split("/")[2])] == "Bearer tok-blue"
    assert got[("reflect", settings.blue_url.split("/")[2])] == "Bearer tok-blue"
    assert got[("schemes", settings.red_url.split("/")[2])] == "Bearer tok-red"
    assert got[("gate", settings.blue_url.split("/")[2])] == "Bearer tok-blue"


# ---------- DB: impersonation is audited, garbage is not ----------


@pytest.mark.usefixtures("per_agent")
async def test_one_agent_posing_as_another_is_audited_garbage_is_not(pg: None, episode: str) -> None:
    from httpx import ASGITransport, AsyncClient

    from app import main

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://bf") as c:
        r = await c.get("/api/vendors", headers=auth("green", episode=episode, token=OWN["red"]))
        assert r.status_code == 401
        r = await c.get("/api/vendors", headers=auth("blue", episode=episode, token="garbage"))
        assert r.status_code == 401
        r = await c.get("/api/vendors", headers=auth("red", episode=episode, token=OWN["red"]))
        assert r.status_code == 200
    rows = await db.fetch("SELECT agent, http_status, result FROM audit_log WHERE episode_id=$1 AND http_status=401", episode)
    assert len(rows) == 1
    row = rows[0]
    assert row["agent"] == "green" and row["result"]["presented_by"] == "red"
    assert OWN["red"] not in str(row["result"])


# ---------- deploy/render-env.sh ----------

BASE = {"PATH": os.defpath, "AGENT_TOKEN": "fixture-agent", "OPERATOR_TOKEN": "fixture-operator", "DRY_RUN": "true"}


def _render(tmp_path: Path, extra: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "runtime.env"
    r = subprocess.run(
        ["sh", str(ROOT / "deploy/render-env.sh"), str(out)], cwd=tmp_path, env=BASE | extra, capture_output=True, text=True, timeout=10, check=False
    )
    return r, out


def _values(path: Path) -> dict[str, str]:
    return {k: v.strip("'") for k, v in (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))}


def test_render_without_per_agent_tokens_falls_back_and_warns(tmp_path: Path) -> None:
    r, out = _render(tmp_path, {})
    assert r.returncode == 0, r.stderr
    v = _values(out)
    assert v["AGENT_TOKEN_RED"] == v["AGENT_TOKEN_GREEN"] == v["AGENT_TOKEN_BLUE"] == "fixture-agent"
    assert "per-agent separation off" in r.stderr and "fixture-agent" not in r.stdout + r.stderr


def test_render_with_three_distinct_tokens(tmp_path: Path) -> None:
    r, out = _render(tmp_path, {"AGENT_TOKEN_RED": "r1", "AGENT_TOKEN_GREEN": "g1", "AGENT_TOKEN_BLUE": "b1"})
    assert r.returncode == 0, r.stderr
    v = _values(out)
    assert (v["AGENT_TOKEN_RED"], v["AGENT_TOKEN_GREEN"], v["AGENT_TOKEN_BLUE"]) == ("r1", "g1", "b1")
    assert oct(out.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize(
    "extra,needle",
    [
        ({"AGENT_TOKEN_RED": "x", "AGENT_TOKEN_GREEN": "x", "AGENT_TOKEN_BLUE": "b"}, "AGENT_TOKEN_RED equals AGENT_TOKEN_GREEN"),
        ({"AGENT_TOKEN_RED": "r", "AGENT_TOKEN_GREEN": "g", "AGENT_TOKEN_BLUE": "g"}, "AGENT_TOKEN_GREEN equals AGENT_TOKEN_BLUE"),
        ({"AGENT_TOKEN_RED": "fixture-operator", "AGENT_TOKEN_GREEN": "g", "AGENT_TOKEN_BLUE": "b"}, "AGENT_TOKEN_RED equals OPERATOR_TOKEN"),
        ({"AGENT_TOKEN_RED": "r"}, "all of AGENT_TOKEN_RED, AGENT_TOKEN_GREEN, AGENT_TOKEN_BLUE or none"),
    ],
)
def test_render_refuses_bad_per_agent_tokens(tmp_path: Path, extra: dict[str, str], needle: str) -> None:
    r, out = _render(tmp_path, extra)
    assert r.returncode != 0
    assert needle in r.stderr
    assert not out.exists()
    for value in extra.values():
        assert f"'{value}'" not in r.stdout + r.stderr
