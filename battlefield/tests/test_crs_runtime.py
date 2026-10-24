"""Credential-free CRS runtime wiring and the actual CI contracts guard. Owner: Dev Ad."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS = {"CRS_USERNAME": "fixture#crs$user", "CRS_PASSWORD": "fixture#crs$pass${UNSET}"}
# Never inherit developer credentials or configuration in renderer/guard subprocesses.
RENDER_ENV = {"PATH": os.defpath, "AGENT_TOKEN": "fixture-agent", "OPERATOR_TOKEN": "fixture-operator", "DRY_RUN": "true"}


def _render(tmp_path: Path, overrides: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path]:
    output = tmp_path / "runtime.env"
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/render-env.sh"), str(output)],
        cwd=tmp_path,
        env=RENDER_ENV | overrides,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, output


def _yaml_block(document: str, header: str) -> str:
    """Extract our indentation-delimited mapping blocks without an undeclared YAML parser."""
    lines = document.splitlines()
    start = lines.index(header) + 1
    indent = len(header) - len(header.lstrip())
    end = start
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    return "\n".join(lines[start:end])


def test_renderer_preserves_literal_crs_credentials_without_logging(tmp_path: Path) -> None:
    result, output = _render(tmp_path, CREDENTIALS)

    assert result.returncode == 0, result.stderr
    rendered = output.read_text()
    for name, value in (RENDER_ENV | CREDENTIALS).items():
        if name == "PATH":
            continue
        assert f"{name}='{value}'" in rendered.splitlines()
    for name in CREDENTIALS:
        assert name in result.stdout  # Names are safe to report; values are not.
    for value in [*CREDENTIALS.values(), RENDER_ENV["AGENT_TOKEN"], RENDER_ENV["OPERATOR_TOKEN"]]:
        assert value not in result.stdout + result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("credentials", [{}, {"CRS_USERNAME": CREDENTIALS["CRS_USERNAME"]}, {"CRS_PASSWORD": CREDENTIALS["CRS_PASSWORD"]}])
def test_renderer_allows_absent_crs_credentials(tmp_path: Path, credentials: dict[str, str]) -> None:
    result, output = _render(tmp_path, credentials)

    assert result.returncode == 0, result.stderr
    lines = output.read_text().splitlines()
    for name in CREDENTIALS:
        assert f"{name}='{credentials.get(name, '')}'" in lines
    assert "CRS_API_KEY=''" in lines  # Keep legacy plumbing without requiring it.
    assert "DRY_RUN='true'" in lines


@pytest.mark.parametrize("name", ["CRS_USERNAME", "CRS_PASSWORD"])
@pytest.mark.parametrize("bad_value", ["fixture'unsafe", "fixture\nunsafe"])
def test_renderer_rejects_unsafe_crs_values_atomically(tmp_path: Path, name: str, bad_value: str) -> None:
    output = tmp_path / "runtime.env"
    output.write_text("unchanged fixture\n")
    result, output = _render(tmp_path, CREDENTIALS | {name: bad_value})

    assert result.returncode != 0
    assert output.read_text() == "unchanged fixture\n"
    assert list(tmp_path.iterdir()) == [output]
    assert name in result.stderr
    for value in [bad_value, *CREDENTIALS.values()]:
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"AGENT_TOKEN": ""},
        {"OPERATOR_TOKEN": ""},
        {"OPERATOR_TOKEN": RENDER_ENV["AGENT_TOKEN"]},
        {"DOMAIN": "fixture.invalid"},
        {"DOMAIN": "fixture.invalid", "CF_ACCESS_TEAM_DOMAIN": "fixture.cloudflareaccess.com"},
        {"DOMAIN": "fixture.invalid", "CF_ACCESS_AUD": "fixture-audience"},
    ],
)
def test_renderer_keeps_token_and_public_access_safeguards(tmp_path: Path, overrides: dict[str, str]) -> None:
    result, output = _render(tmp_path, CREDENTIALS | overrides)

    assert result.returncode != 0
    assert not output.exists()
    for value in CREDENTIALS.values():
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("paths", "expected_code"),
    [
        ([], 0),
        (["blue/audit/crs.py"], 0),
        (["contracts/ext/red/01_fixture.sql"], 0),
        (["contracts/ext/green/01_fixture.sql"], 0),
        (["contracts/ext/blue/01_crs_profiles.sql"], 0),
        (["contracts/ext/fe/nested/01_fixture.sql"], 0),
        (["contracts/ext/blue/01_crs_profiles.sql", "contracts/ext/red/01_fixture.sql"], 0),
        (["contracts/schema.sql"], 1),
        (["contracts/ledger-api.yaml"], 1),
        (["contracts/events.md"], 1),
        (["contracts/ext/blue/01_crs_profiles.sql", "contracts/schema.sql"], 1),
        (["contracts/ext/README.md"], 1),
        (["contracts/ext/other/01_fixture.sql"], 1),
        (["contracts/ext/blueish/01_fixture.sql"], 1),
        (["contracts/ext/blue.sql"], 1),
        (["contracts/schema.sql", "contracts/CHANGELOG.md"], 0),
        (["contracts/schema.sql", "contracts/ext/blue/01_crs_profiles.sql", "contracts/CHANGELOG.md"], 0),
        (["contracts/CHANGELOG.md"], 0),
        (["contracts/schema.sql", "contracts/ext/blue/CHANGELOG.md"], 1),
        (["contracts/core\nwith-newline.sql"], 1),
    ],
)
def test_real_contracts_guard(paths: list[str], expected_code: int) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / ".github/scripts/check_contracts.py")],
        cwd=ROOT,
        env={"PATH": os.defpath},
        input=b"".join(path.encode() + b"\0" for path in paths),
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == expected_code, result.stderr
    assert (b"::error::" in result.stdout) == (expected_code != 0)


def test_compose_credentials_are_empty_by_default_and_blue_only() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    blue = _yaml_block(compose, "  blue:")
    environment = _yaml_block(blue, "    environment:")
    example = (ROOT / ".env.example").read_text().splitlines()

    for name in CREDENTIALS:
        assert f"{name}=" in example
        assert f"      {name}: ${{{name}:-}}" in environment.splitlines()
        assert name not in compose.replace(blue, "")
        assert len(re.findall(rf"(?m)^\s*{name}:", compose)) == 1
        assert name not in _yaml_block(blue, "    build:")
    assert "      CRS_API_KEY: ${CRS_API_KEY:-}" in environment.splitlines()


def test_deploy_forwards_both_credentials_only_from_production_secrets() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    build = _yaml_block(workflow, "  build:")
    roll = _yaml_block(workflow, "  roll:")
    ssh = _yaml_block(roll, "      - uses: appleboy/ssh-action@v1")
    environment = _yaml_block(ssh, "        env:")
    forwarded = re.search(r"(?m)^          envs: (.+)$", ssh)
    assert forwarded is not None
    forwarded_names = forwarded[1].split(",")
    assert "    environment: production" in roll.splitlines()
    assert "build-args:" not in workflow

    for name in CREDENTIALS:
        assert f"          {name}: ${{{{ secrets.{name} }}}}" in environment.splitlines()
        assert forwarded_names.count(name) == 1
        assert name not in build
        assert name not in workflow.replace(ssh, "")
    assert "CRS_API_KEY" in forwarded_names
    assert "sh deploy/render-env.sh .env" in ssh


def test_ci_runs_the_guard_and_its_regression_tests() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    guard = _yaml_block(workflow, "  contracts-guard:")
    assert "        shell: bash" in guard.splitlines()  # Explicit bash enables pipefail in Actions.
    assert 'git diff --name-only --no-renames -z "$BASE_REF"...HEAD | python3 .github/scripts/check_contracts.py' in guard
    assert "BASE_REF: origin/${{ github.base_ref || 'main' }}" in guard
    assert "|| true" not in guard
    assert "  ownership-guard:" in workflow.splitlines()
    filters = re.search(r"(?m)^            battlefield: (.+)$", workflow)
    assert filters is not None
    for path in [
        ".github/scripts/check_contracts.py",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
        "docker-compose.yml",
        "deploy/render-env.sh",
    ]:
        assert f"'{path}'" in filters[1]
