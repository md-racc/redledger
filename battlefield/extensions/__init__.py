"""Team extension routers. Owner: Dev Ad (loader); each file is owned by the team in its prefix.

Drop a file here named `<area>_<name>.py` where area ∈ red | green | blue | fe. It must define
`router = APIRouter()`. It is mounted automatically at `/api/x/<area>/...`. CI lets a `red/`
branch edit `battlefield/extensions/red_*.py` and `contracts/ext/red/*.sql`, and nothing else
in battlefield. Same for green, blue, fe (frontend branches).

Rules for an extension file:
  - Use `from app import db` for queries and `from app.auth import bearer, caller, allow` for auth.
  - Only touch tables prefixed with your area (`red_*`, ...) plus reads of core tables.
    Never write core tables from an extension; that's what the Ledger API is for.
  - Emit events via `from app.events import bus` with type `x.<area>.<name>`.
  - If it needs a table, add `contracts/ext/<area>/<nn>_<name>.sql` (CREATE TABLE IF NOT EXISTS).
  - Public (no-token) routes are allowed only in `fe_*` extensions and must be read-mostly
    and rate-tolerant; mark them with `@router.get(..., dependencies=[])` and say so in a comment.

See `fe_example.py` for the shape. Delete it when the first real one lands.
"""

from __future__ import annotations

import importlib
import pkgutil

import structlog
from fastapi import APIRouter, FastAPI

log = structlog.get_logger(__name__)
AREAS = ("red", "green", "blue", "fe")


def mount_all(app: FastAPI, prefix: str = "/api/x") -> list[str]:
    mounted: list[str] = []
    for mod in pkgutil.iter_modules(__path__):
        area = mod.name.split("_", 1)[0]
        if area not in AREAS or "_" not in mod.name:
            log.warning("extension_skipped_bad_name", name=mod.name)
            continue
        try:
            m = importlib.import_module(f"{__name__}.{mod.name}")
            router = getattr(m, "router", None)
            if not isinstance(router, APIRouter):
                log.warning("extension_has_no_router", name=mod.name)
                continue
            app.include_router(router, prefix=f"{prefix}/{area}", tags=[f"x:{area}"])
            mounted.append(f"{prefix}/{area} ← {mod.name}")
        except Exception as e:  # one broken extension must not take battlefield down
            log.error("extension_failed", name=mod.name, error=str(e))
    return mounted
