"""Exercise the extension with real battlefield auth, without DB or developer settings."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def profile_app(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "battlefield"
    package = ModuleType("app")
    package.__path__ = [str(root / "app")]
    db = SimpleNamespace(fetchrow=AsyncMock(), fetchval=AsyncMock(return_value=5))
    bus = SimpleNamespace(emit=AsyncMock())
    for name, module in {
        "app": package,
        "app.config": SimpleNamespace(settings=SimpleNamespace(agent_token="test-agent", operator_token="test-operator")),
        "app.turns": SimpleNamespace(),
        "app.db": db,
        "app.events": SimpleNamespace(bus=bus),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    load("app.auth", root / "app" / "auth.py")
    extension = load("crs_extension_under_test", root / "extensions" / "blue_crs.py")
    app = FastAPI()
    app.include_router(extension.router, prefix="/api/x/blue")
    return app, db, bus


async def test_operator_binding_immutable_and_no_identity_in_event(profile_app):
    app, db, bus = profile_app
    db.fetchrow.side_effect = [{"id": "emp"}, {"employee_id": "emp"}, {"id": "emp"}, None]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ledger") as client:
        url = "/api/x/blue/crs/episodes/ep/employees/emp"
        headers = {"Authorization": "Bearer test-operator"}
        assert (await client.put(url, headers=headers, json={"persona_id": "P01"})).status_code == 200
        assert (await client.put(url, headers=headers, json={"persona_id": "P12"})).status_code == 409
        assert (await client.put(url, headers=headers, json={"persona_id": "arbitrary"})).status_code == 422
        assert (await client.put(url, headers=headers, json={"persona_id": "P01", "ssn": "private"})).status_code == 422
    assert bus.emit.await_args.args == ("ep", 5, "x.blue.crs_profile_bound", {"employee_id": "emp"})


@pytest.mark.parametrize("agent,status", [("blue", 200), ("green", 403), ("red", 403), (None, 403)])
async def test_profile_read_blue_only_and_episode_scoped(profile_app, agent, status):
    app, db, _ = profile_app
    db.fetchrow.return_value = {"persona_id": "P01"}
    headers = {"Authorization": "Bearer test-agent" if agent else "Bearer test-operator"}
    if agent:
        headers |= {"X-Agent": agent, "X-Episode": "ep", "X-Day": "5"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ledger") as client:
        response = await client.get("/api/x/blue/crs/employees/emp", headers=headers)
        assert response.status_code == status
        assert (await client.put("/api/x/blue/crs/episodes/ep/employees/emp", headers=headers, json={"persona_id": "P01"})).status_code == (
            200 if not agent else 403
        )
    if agent == "blue":
        assert db.fetchrow.await_args.args[1:] == ("ep", "emp")
