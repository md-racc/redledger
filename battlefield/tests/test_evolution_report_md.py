"""Unit: report.md rendering, the export bundle layout and the secret scan (scripts/evolution_report.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import evolution_report as er

from app.evolution.report import diff

SAMPLE = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "lineages" / "sample-report.json").read_text())


def test_render_md_has_every_section_in_order_and_is_deterministic() -> None:
    md = er.render_md(SAMPLE)
    assert md == er.render_md(json.loads(json.dumps(SAMPLE)))
    heads = [line for line in md.splitlines() if line.startswith("## ")]
    assert heads == [
        "## 1. Run card",
        "## 2. Score per generation",
        "## 3. Red tactic mix",
        "## 4. Blue rules",
        "## 5. Who beat whom",
        "## 6. Green",
        "## 7. Playbook timeline",
        "## 8. What each agent was shown",
    ]
    assert "| 3 (demo) | 50 |" in md
    assert "`evolved:split_v2` (g2, from threshold_split)" in md
    assert "- Learned: `learned:ghost_vendor` (g2)" in md
    assert "Partial" not in md


def test_render_md_marks_partial_and_escapes_pipes() -> None:
    rep = json.loads(json.dumps(SAMPLE))
    rep["partial"], rep["lineage"]["status"] = True, "running"
    rep["playbooks"]["red"][1]["rationale"] = "a|b"
    md = er.render_md(rep)
    assert "> Partial: the lineage is `running`." in md
    assert "a\\|b" in md


def test_diff_is_structural() -> None:
    assert diff({"a": 1, "b": {"c": 2, "d": 3}}, {"a": 1, "b": {"c": 5}, "e": [1]}) == {
        "added": {"e": [1]},
        "removed": {"b.d": 3},
        "changed": {"b.c": {"from": 2, "to": 5}},
    }
    assert diff({}, {}) == {"added": {}, "removed": {}, "changed": {}}
    assert diff([1], [2]) == {"added": {}, "removed": {}, "changed": {"": {"from": [1], "to": [2]}}}


def test_bundle_files_layout() -> None:
    doc = {
        "lineage": {"id": "ln_1"},
        "playbooks": {"red": [{"version": 0}, {"version": 1}], "blue": [{"version": 0}]},
        "generations": [
            {
                "generation": 1,
                "episode": {"id": "ep_1"},
                "score": {"dollars_extracted": 1},
                "credits": {"by_day": [], "total": {}},
                "events": [{"id": 1}, {"id": 2}],
                "audit_log": [],
                "verdicts": [],
                "attacks": [{"id": "att_1"}],
                "debriefs": [],
                "playbooks": {"red": [{"version": 1}]},
            }
        ],
    }
    files = er.bundle_files(doc)
    assert sorted(files) == [
        "gen-1/attacks.json",
        "gen-1/audit_log.jsonl",
        "gen-1/credits.json",
        "gen-1/debriefs.jsonl",
        "gen-1/episode.json",
        "gen-1/events.jsonl",
        "gen-1/playbooks/red-v1.json",
        "gen-1/score.json",
        "gen-1/verdicts.jsonl",
        "lineage.json",
        "playbooks/blue-v0.json",
        "playbooks/red-v0.json",
        "playbooks/red-v1.json",
    ]
    assert files["gen-1/events.jsonl"] == '{"id": 1}\n{"id": 2}\n'


def test_secret_scan_refuses_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert er.scan("note: task-assessment_for_vendor_x", er.HARD) == []
    hits = er.scan('{"k": "sk-' + "a" * 30 + '"}', er.HARD)
    assert hits == ["sk-a…(33 chars)"]
    with pytest.raises(SystemExit) as e:
        er._write_checked(tmp_path / "ln_1", {"report.json": "Bearer " + "x" * 20})
    assert e.value.code == 3 and not (tmp_path / "ln_1").exists()
    assert "x" * 20 not in capsys.readouterr().err  # hits are redacted


def test_write_checked_writes_all_and_ignores_runs(tmp_path: Path) -> None:
    er._write_checked(tmp_path / "ln_1", {"report.json": "{}\n", "gen-1/a.json": "[]\n"})
    assert (tmp_path / "ln_1" / "report.json").read_text() == "{}\n"
    assert (tmp_path / "ln_1" / "gen-1" / "a.json").read_text() == "[]\n"
    assert (tmp_path / ".gitignore").read_text() == "*\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".gitignore", "ln_1"]  # no temp dir left behind
