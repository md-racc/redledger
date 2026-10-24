"""Operator-bound fictional profiles; Blue reads only its current episode."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import db
from app.auth import Caller, allow, bearer
from app.events import bus

router = APIRouter()


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: Literal["P01", "P12", "P16"]


@router.put("/crs/episodes/{episode_id}/employees/{employee_id}", dependencies=[Depends(bearer)])
async def bind_profile(episode_id: str, employee_id: str, body: Profile) -> dict[str, bool]:
    employee = await db.fetchrow("SELECT id FROM employees WHERE episode_id=$1 AND id=$2", episode_id, employee_id)
    if employee is None:
        raise HTTPException(404, "employee not found in episode")
    row = await db.fetchrow(
        "INSERT INTO blue_crs_employee_profiles (episode_id, employee_id, persona_id) VALUES ($1,$2,$3) "
        "ON CONFLICT (episode_id, employee_id) DO UPDATE SET persona_id=EXCLUDED.persona_id "
        "WHERE blue_crs_employee_profiles.persona_id=EXCLUDED.persona_id RETURNING employee_id",
        episode_id,
        employee_id,
        body.persona_id,
    )
    if row is None:
        raise HTTPException(409, "profile binding is immutable; use a new synthetic employee")
    day = await db.fetchval("SELECT current_day FROM episodes WHERE id=$1", episode_id) or 0
    await bus.emit(episode_id, day, "x.blue.crs_profile_bound", {"employee_id": employee_id}, agent="human")
    return {"ok": True}


@router.get("/crs/employees/{employee_id}")
async def employee_profile(employee_id: str, c: Caller = Depends(allow("blue", operator=False))) -> dict[str, str]:
    row = await db.fetchrow("SELECT persona_id FROM blue_crs_employee_profiles WHERE episode_id=$1 AND employee_id=$2", c.episode_id, employee_id)
    return {"persona_id": row["persona_id"]} if row else {}
