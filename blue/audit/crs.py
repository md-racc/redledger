"""Sandbox-only identity checks. Request bodies are pinned fictional sponsor personas."""

from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

BASE_URL = "https://api-sandbox.stitchcredit.com/api"
IDENTITY_PATH = "/transunion/identity-manager-verification/basic"
CHECK_TIMEOUT = 7.0
# Exact identity request bodies, without expected decisions, from sponsor package v1.1.2.
PERSONAS = json.loads(Path(__file__).with_name("crs_personas.json").read_text())


class IdentityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["verified", "mismatch", "review", "unknown"] = "unknown"


def parse_identity(body: Any) -> IdentityResult:
    """Only an explicitly delivered, successful identity product can supply evidence."""
    try:
        if not isinstance(body, dict) or body.get("errorMessages"):
            return IdentityResult()
        products = body["addOnProducts"]
        matches = [p for p in products if isinstance(p, dict) and "idManagerVerification" in p]
        if len(matches) != 1 or matches[0].get("status") != "DELIVERED":
            return IdentityResult()
        result = matches[0]["idManagerVerification"]
        if result.get("searchStatus") not in {"CLEAR", "HIT"}:
            return IdentityResult()
        messages = result["messages"]
        if not isinstance(messages, list) or any(not isinstance(m, dict) or not isinstance(m.get("code"), str) for m in messages):
            return IdentityResult()
        codes = {m["code"] for m in messages}
        if codes - {"2101", "2201", "2202", "2301", "2401"}:
            return IdentityResult()
        if "2401" in codes or codes == {"2101"}:
            return IdentityResult(status="review")
        if codes & {"2201", "2202", "2301"}:
            return IdentityResult(status="mismatch")
        # Sponsor package v1.1.2 (personas.json notes): "messages: empty = verified". The sandbox
        # returns searchStatus HIT with no messages for a cleanly matched identity (observed on the
        # approved P01 probe), so verified must not be conditioned on CLEAR.
        return IdentityResult(status="verified" if not codes else "unknown")
    except (KeyError, TypeError, AttributeError):
        return IdentityResult()


class CRSClient:
    def __init__(self, username: str = "", password: str = ""):
        self._username, self._password = username, password
        self._token: str | None = None
        self._login_attempted = False

    @property
    def configured(self) -> bool:
        return bool(self._username and self._password)

    async def verify(self, persona_id: str, employee_name: Any, *, dry_run: bool) -> IdentityResult:
        persona = PERSONAS.get(persona_id)
        if (
            dry_run
            or not self.configured
            or persona is None
            or not isinstance(employee_name, str)
            or employee_name.strip().casefold() != f"{persona['firstName']} {persona['lastName']}".casefold()
        ):
            return IdentityResult()
        try:
            async with asyncio.timeout(CHECK_TIMEOUT):
                async with httpx.AsyncClient(timeout=3.0, follow_redirects=False, trust_env=False) as client:
                    if self._token is None:
                        if self._login_attempted:
                            return IdentityResult()
                        # Latch BEFORE I/O: an ambiguous or failed login is never retried.
                        self._login_attempted = True
                        login = await client.post(f"{BASE_URL}/users/login", json={"username": self._username, "password": self._password})
                        login.raise_for_status()
                        token = login.json().get("token")
                        if not isinstance(token, str) or not token.strip() or len(token) > 16000:
                            return IdentityResult()
                        self._token = token
                    response = await client.post(
                        f"{BASE_URL}{IDENTITY_PATH}", json=dict(persona), headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
                    )
                    if response.status_code == 401:
                        self._token = None
                    response.raise_for_status()
                    return parse_identity(response.json())
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            # Never put exception bodies, credentials, identities or provider prose into logs.
            return IdentityResult()


@lru_cache(maxsize=1)
def crs_client() -> CRSClient:
    return CRSClient(os.environ.get("CRS_USERNAME", ""), os.environ.get("CRS_PASSWORD", ""))
