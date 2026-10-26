"""Resolve the relocated Compose files without reading local credentials or starting services."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/compose"


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI is not installed")
@pytest.mark.parametrize("overlay", [None, "dev", "mock", "prod"])
def test_compose_layout_preserves_paths_and_isolation(overlay: str | None, tmp_path: Path) -> None:
    command = [
        "docker",
        "compose",
        "--env-file",
        os.devnull,
        "--project-directory",
        str(ROOT),
        "-f",
        str(COMPOSE / "docker-compose.yml"),
    ]
    if overlay:
        command += ["-f", str(COMPOSE / f"docker-compose.{overlay}.yml")]
    command += ["config", "--format", "json"]
    result = subprocess.run(
        command,
        cwd=tmp_path,  # Resolution must not depend on the caller being beside the YAML files.
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_REPO": "fixture/redledger",
            "DOMAIN": "fixture.invalid",
            "AGENT_TOKEN": "fixture-shared",
            "AGENT_TOKEN_RED": "fixture-red",
            "AGENT_TOKEN_GREEN": "fixture-green",
            "AGENT_TOKEN_BLUE": "fixture-blue",
            "OPERATOR_TOKEN": "fixture-operator",
            "DRY_RUN": "true",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    config = json.loads(result.stdout)
    services = config["services"]
    assert config["name"] == ROOT.name.lower()
    assert config["networks"]["data"]["internal"] is True
    for agent in ["red", "green", "blue"]:
        assert set(services[agent]["networks"]) == {"agents"}
        assert "DATABASE_URL" not in services[agent]["environment"]
    assert set(services["frontend"]["networks"]) == {"edge"}
    assert set(services["postgres"]["networks"]) == {"data"}
    assert set(services["battlefield"]["networks"]) == {"edge", "agents", "data"}

    for name, service in services.items():
        if build := service.get("build"):
            context = Path(build["context"])
            assert context == (ROOT / "frontend" if name == "frontend" else ROOT)
            assert (context / build.get("dockerfile", "Dockerfile")).is_file()
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                source = Path(mount["source"])
                assert source.is_relative_to(ROOT)
                assert source.exists()

    if overlay == "dev":
        assert all(services[agent]["environment"]["DRY_RUN"] == "true" for agent in ["red", "green", "blue"])
    elif overlay == "mock":
        assert all("mock_agents.server:app" in services[agent]["command"] for agent in ["red", "green", "blue"])
    elif overlay == "prod":
        assert all(not services[name].get("ports") for name in ["postgres", "battlefield", "red", "green", "blue", "frontend"])
        assert all("build" not in services[name] for name in ["battlefield", "red", "green", "blue", "frontend"])
        assert set(services["caddy"]["networks"]) == {"edge"}
