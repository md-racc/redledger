"""deploy/render-env.sh: ADMIN_KEY and the public read-only mode (Cloudflare Access off). Owner: Dev Ad.

Runs the renderer in a subprocess with a clean environment, like test_per_agent_tokens.py.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = {"PATH": os.defpath, "AGENT_TOKEN": "fixture-agent", "OPERATOR_TOKEN": "fixture-operator", "DRY_RUN": "true"}
KEY = "fixture-admin-key-0123456789abcdef0123"
CF = {"CF_ACCESS_TEAM_DOMAIN": "fixture.cloudflareaccess.com", "CF_ACCESS_AUD": "fixture-audience"}


def _render(tmp_path: Path, extra: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "runtime.env"
    r = subprocess.run(
        ["sh", str(ROOT / "deploy/render-env.sh"), str(out)], cwd=tmp_path, env=BASE | extra, capture_output=True, text=True, timeout=10, check=False
    )
    return r, out


def _values(path: Path) -> dict[str, str]:
    return {k: v.strip("'") for k, v in (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))}


def test_public_read_only_mode_needs_admin_key_and_renders_it(tmp_path: Path) -> None:
    r, out = _render(tmp_path, {"DOMAIN": "fixture.invalid", "ADMIN_KEY": KEY})
    assert r.returncode == 0, r.stderr
    assert _values(out)["ADMIN_KEY"] == KEY
    assert "Cloudflare Access off" in r.stderr
    assert KEY not in r.stdout + r.stderr


def test_access_mode_still_works_with_or_without_admin_key(tmp_path: Path) -> None:
    r, out = _render(tmp_path, {"DOMAIN": "fixture.invalid"} | CF)
    assert r.returncode == 0, r.stderr
    assert _values(out)["ADMIN_KEY"] == ""
    r, out = _render(tmp_path, {"DOMAIN": "fixture.invalid", "ADMIN_KEY": KEY} | CF)
    assert r.returncode == 0, r.stderr
    assert _values(out)["ADMIN_KEY"] == KEY and "Cloudflare Access off" not in r.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"DOMAIN": "fixture.invalid"},  # Access off and no admin key: the operator proxy would be open
        {"DOMAIN": "fixture.invalid", "ADMIN_KEY": KEY, "CF_ACCESS_AUD": "fixture-audience"},  # partial Access
        {"ADMIN_KEY": "too-short"},
        {"ADMIN_KEY": " " * 40},
        {"ADMIN_KEY": BASE["OPERATOR_TOKEN"] + "x" * 32, "OPERATOR_TOKEN": BASE["OPERATOR_TOKEN"] + "x" * 32},
        {"ADMIN_KEY": "a" * 40, "AGENT_TOKEN_RED": "a" * 40, "AGENT_TOKEN_GREEN": "g" * 40, "AGENT_TOKEN_BLUE": "b" * 40},
    ],
)
def test_refuses_unsafe_admin_key_configs(tmp_path: Path, overrides: dict[str, str]) -> None:
    r, out = _render(tmp_path, overrides)
    assert r.returncode != 0
    assert not out.exists()
    secret = overrides.get("ADMIN_KEY", "")
    if secret.strip():
        assert secret not in r.stdout + r.stderr


def test_local_render_without_domain_allows_blank_admin_key(tmp_path: Path) -> None:
    r, out = _render(tmp_path, {})
    assert r.returncode == 0, r.stderr
    assert _values(out)["ADMIN_KEY"] == ""


def test_renders_elevenlabs_without_printing_the_key(tmp_path: Path) -> None:
    secret = "fixture-elevenlabs-key-0123456789"
    r, out = _render(tmp_path, {"ELEVENLABS_API_KEY": secret, "ELEVENLABS_STT_MODEL": "scribe_v2"})
    assert r.returncode == 0, r.stderr
    v = _values(out)
    assert v["ELEVENLABS_API_KEY"] == secret and v["ELEVENLABS_STT_MODEL"] == "scribe_v2"
    assert secret not in r.stdout + r.stderr
