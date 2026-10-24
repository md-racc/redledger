"""Unit: row_to_dict / rows_to_list provenance stripping. No DB."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app import db

ROW = {"id": "inv_1", "amount": Decimal("12.50"), "origin": "red", "attack_id": "atk_1", "origin_of_source": "red", "ts": datetime(2026, 1, 2, 3, 4)}


def test_hide_strips_every_hidden_column() -> None:
    d = db.row_to_dict(ROW, hide=True)  # type: ignore[arg-type]
    assert d is not None
    assert not (set(d) & db.HIDDEN_COLUMNS)
    assert d["id"] == "inv_1"


def test_operator_view_keeps_provenance_and_converts_types() -> None:
    d = db.row_to_dict(ROW)  # type: ignore[arg-type]
    assert d is not None
    assert d["origin"] == "red" and d["attack_id"] == "atk_1" and d["origin_of_source"] == "red"
    assert d["amount"] == 12.5 and isinstance(d["amount"], float)
    assert d["ts"] == "2026-01-02T03:04:00"
    assert db.row_to_dict({"d": date(2026, 1, 2)})["d"] == "2026-01-02"  # type: ignore[arg-type,index]


def test_none_and_lists() -> None:
    assert db.row_to_dict(None) is None
    out = db.rows_to_list([ROW, ROW], hide=True)  # type: ignore[list-item]
    assert len(out) == 2 and all("origin" not in r for r in out)


def test_hidden_columns_cover_provenance() -> None:
    assert {"origin", "attack_id", "origin_of_source"} <= db.HIDDEN_COLUMNS
