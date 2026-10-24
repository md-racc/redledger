"""Evolution report and lineage log bundle, from the operator API. Owner: Dev Ad.

docs/EVOLUTION-DESIGN.md §6–§7. Standard library only, so `make` can run it with plain python3.

    python3 battlefield/scripts/evolution_report.py report LN   # runs/<LN>/report.json + report.md
    python3 battlefield/scripts/evolution_report.py export LN   # runs/<LN>/lineage.json + gen-<g>/...
    python3 battlefield/scripts/evolution_report.py report-file LN FILE   # same, from a saved report JSON
    python3 battlefield/scripts/evolution_report.py export-file LN FILE   # same, from a saved export JSON

The *-file forms are what `make prod-evolution-report` / `make prod-lineage-export` use: deploy/prod.sh
fetches the JSON on the VM (the operator token never leaves it) into a temp file outside the repo.

Environment: API (default http://localhost:8000), TOKEN (operator token), RUNS_DIR (default runs).
`report` writes `/api/fe/lineages/{id}/report` verbatim as report.json and renders report.md from it.
`export` reads `/api/lineages/{id}/export`:
    {"lineage": {...}, "playbooks": {agent: [every version]},
     "generations": [{"generation", "episode_id", "seed", "status", "episode": {...}, "score": {...},
                      "credits": {"by_day": [...], "total": {...}}, "events": [...], "audit_log": [...],
                      "verdicts": [...], "attacks": [...], "debriefs": [...], "playbooks": {agent: [...]}}]}
and writes lineage.json, playbooks/<agent>-v<n>.json (full history) and per generation gen-<g>/
{episode.json, events.jsonl, audit_log.jsonl, verdicts.jsonl, debriefs.jsonl, attacks.json, score.json,
credits.json, playbooks/<agent>-v<n>.json}. Both run the same secret scan as `make prod-record` (deploy/prod.sh):
a hard hit (key/token shape) writes nothing and exits 3; a soft hit (long hex/base64) warns.
runs/ ignores itself (the script writes runs/.gitignore = `*`); the export contains ground truth
(origin), never commit or publish it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HARD = [
    r"(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}",
    r"(^|[^A-Za-z0-9])fk-[A-Za-z0-9_-]{20,}",
    r"(^|[^A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}",
    r"(^|[^A-Za-z0-9])github_pat_[A-Za-z0-9_]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"(^|[^A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    r"-----BEGIN [A-Z ]*PRIVATE KEY",
    r"[Bb]earer [A-Za-z0-9._~+/=-]{16,}",
    r"\[REDACTED\]",
]
SOFT = [r"[0-9a-fA-F]{32,}", r"[A-Za-z0-9+/_-]{40,}={0,2}"]
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Soft hits that are plainly identifiers, not secrets: a uuid4 in hex form (tool-use / idempotency keys),
# or anything carrying a short id prefix (ep_, ln_, inv_, atk_, toolu_, ...). Base64 hits also follow
# deploy/prod.sh: random strings have >= 4 digits and a letter, and URL paths are skipped.
UUID4_HEX = re.compile(r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}")
# Our own id prefixes (db.new_id + Droid tool-use ids). Deliberately a closed list: `sk_live_…`-style
# secrets also start with a short word and an underscore, and must still warn.
_IDS = "atk|bnk|emp|ep|esc|exp|flg|gl|inv|ln|pay|po|rpt|vch|vd|ven|toolu"
ID_PREFIX = re.compile(rf"(?<![A-Za-z])(?:{_IDS})_$")
ID_SELF = re.compile(rf"(?:{_IDS})_")


def scan(text: str, patterns: list[str]) -> list[str]:
    """Redacted hits (first 4 chars + length), never the match itself."""
    hits = []
    for p in patterns:
        for m in re.finditer(p, text):
            s = m.group(0)
            if p.startswith("(^|") and s and not s[0].isalnum():
                s = s[1:]  # the left-boundary character the pattern matched
            hits.append(f"{s[:4]}…({len(s)} chars)")
    return hits


def soft_scan(text: str) -> list[str]:
    """Like scan(text, SOFT), minus hits that are identifiers (see UUID4_HEX / ID_PREFIX)."""
    hits = []
    for p in SOFT:
        for m in re.finditer(p, text):
            s = m.group(0)
            before = text[max(0, m.start() - 9) : m.start()]
            if ID_PREFIX.search(before) or ID_SELF.match(s):
                continue  # ep_<hex>, toolu_<base64>, ...
            if p == SOFT[0] and len(s) == 32 and UUID4_HEX.fullmatch(s.lower()):
                continue  # uuid4().hex: a generated key, not a secret (a real 32-hex secret has ~1/64 odds of this shape)
            if p == SOFT[1] and (sum(c.isdigit() for c in s) < 4 or not any(c.isalpha() for c in s) or s.startswith("/")):
                continue
            hits.append(f"{s[:4]}…({len(s)} chars)")
    return hits


def get(path: str) -> Any:
    api = os.environ.get("API", "http://localhost:8000").rstrip("/")
    req = urllib.request.Request(f"{api}{path}", headers={"Authorization": f"Bearer {os.environ.get('TOKEN', 'change-me')}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"GET {path} -> {e.code} {e.read().decode(errors='replace')[:200]}")
    except urllib.error.URLError as e:
        sys.exit(f"GET {path} failed: {e.reason}")


def _money(x: Any) -> str:
    return f"${float(x or 0):,.0f}"


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["_none_", ""]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return out + [""]


def _diff_line(d: dict[str, Any]) -> str:
    parts = [f"+{k}" for k in d.get("added", {})] + [f"-{k}" for k in d.get("removed", {})] + [f"~{k}" for k in d.get("changed", {})]
    return ", ".join(parts) if parts else "no change"


def render_md(rep: dict[str, Any]) -> str:
    """report.json → report.md, sections in docs/EVOLUTION-DESIGN.md §7 order. Deterministic."""
    ln, card, gens = rep["lineage"], rep["run_card"], rep["generations"]
    md = [f"# Evolution report: {ln.get('name') or ln['id']}", ""]
    if rep.get("partial"):
        md += [f"> Partial: the lineage is `{ln['status']}`.", ""]
    md += ["## 1. Run card", ""]
    md += [
        f"- Lineage `{ln['id']}`, status `{ln['status']}`, base seed {ln['base_seed']}",
        f"- Generations: {card['generations']} headless" + (f" + demo {card['demo_generations']}" if card["demo_generations"] else ""),
        f"- Seeds: {', '.join(str(s) for s in card['seeds']) or 'none yet'}",
        f"- Days per generation: {card['days']}, controller mode `{card['controller_mode']}`",
        f"- Models: {card['models'] or 'n/a (agent-side)'}; git SHA: {card['git_sha'] or 'n/a'}",
        "- Credits: " + (", ".join(f"g{c['generation']} {c['factory_credits']}" for c in card["credits"]) or "none"),
        "",
    ]
    md += ["## 2. Score per generation", ""]
    md += _table(
        ["gen", "seed", "extracted", "blocked", "FP cost", "latency (days)", "caught / launched"],
        [
            [
                g["generation"] if not g["demo"] else f"{g['generation']} (demo)",
                g["seed"],
                _money(g["score"]["dollars_extracted"]),
                _money(g["score"]["dollars_blocked"]),
                _money(g["score"]["false_positive_cost"]),
                g["score"]["detection_latency_days"] if g["score"]["detection_latency_days"] is not None else "-",
                f"{g['score']['attacks_caught']} / {g['score']['attacks_launched']}",
            ]
            for g in gens
        ],
    )
    md += ["## 3. Red tactic mix", ""]
    md += _table(
        ["gen", "scheme", "launched", "outcomes", "extracted"],
        [
            [g["generation"], s, m["launched"], ", ".join(f"{k} {v}" for k, v in sorted(m["outcomes"].items())), _money(m["amount_extracted"])]
            for g in gens
            for s, m in sorted(g["red_mix"].items())
        ],
    )
    evolved = rep["red"]["evolved_schemes"]
    md += ["Evolved schemes: " + (", ".join(f"`{e['scheme_id']}` (g{e['first_generation']}, from {e['parent'] or '?'})" for e in evolved) or "none"), ""]
    md += ["## 4. Blue rules", ""]
    md += _table(
        ["gen", "rule", "fired", "on red", "on legit", "precision", "recall"],
        [
            [
                g["generation"],
                f"`{r['rule_id']}`",
                r["fired"],
                r["on_red"],
                r["on_legit"],
                r["precision"] if r["precision"] is not None else "-",
                r["recall"] if r["recall"] is not None else "-",
            ]
            for g in gens
            for r in g["blue_rules"]
        ],
    )
    blue = rep["blue"]
    md += [
        "- Learned: " + (", ".join(f"`{r['rule_id']}` (g{r['first_generation']})" for r in blue["learned_rules"]) or "none"),
        "- New after generation 1: " + (", ".join(f"`{r['rule_id']}` (g{r['first_generation']})" for r in blue["new_rules"]) or "none"),
        "- Retired: " + (", ".join(f"`{r['rule_id']}` (last g{r['last_generation']})" for r in blue["retired_rules"]) or "none"),
        "",
    ]
    md += ["## 5. Who beat whom", ""]
    md += _table(
        ["gen", "scheme", "attacks", "caught", "missed", "rules that fired (attacks)"],
        [
            [g["generation"], s, m["attacks"], m["caught"], m["missed"], ", ".join(f"`{k}` {v}" for k, v in m["rules"].items()) or "-"]
            for g in gens
            for s, m in g["who_beat_whom"].items()
        ],
    )
    md += ["## 6. Green", ""]
    md += _table(
        ["gen", "actions", "legit processed", "legit blocked", "fraud paid"],
        [[g["generation"], g["green"]["actions"], g["green"]["legit_processed"], g["green"]["legit_blocked"], _money(g["green"]["fraud_paid"])] for g in gens],
    )
    md += ["## 7. Playbook timeline", ""]
    for agent in ("red", "green", "blue"):
        md += [f"### {agent}", ""]
        md += _table(
            ["version", "gen", "day", "source", "rationale", "diff"],
            [
                [v["version"], v["generation"], v["day"] if v["day"] is not None else "-", v["source"], v["rationale"] or "-", _diff_line(v["diff"])]
                for v in rep["playbooks"].get(agent, [])
            ],
        )
    md += ["## 8. What each agent was shown", ""]
    md += _table(
        ["gen", "agent", "daily debriefs", "reviews", "items"],
        [[g["generation"], a, d["daily"], d["aar"], d["items"]] for g in gens for a, d in g["disclosures"].items()],
    )
    return "\n".join(md).rstrip() + "\n"


def _write_checked(dest: Path, files: dict[str, str]) -> None:
    """Scan every file, then write them all (via a temp dir) or nothing."""
    hard = {name: h for name, text in files.items() if (h := scan(text, HARD))}
    if hard:
        for name, h in hard.items():
            print(f"REFUSED {name}: {', '.join(h)}", file=sys.stderr)
        print("Looks like a key or token; nothing written.", file=sys.stderr)
        sys.exit(3)
    for name, text in files.items():
        if h := soft_scan(text):
            print(f"WARNING {name}: long hex/base64 strings ({len(h)}); check before sharing", file=sys.stderr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ignore = dest.parent / ".gitignore"  # runs/ ignores itself: bundles hold ground truth and are never committed
    if not ignore.exists():
        ignore.write_text("*\n")
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    for name, text in files.items():
        (tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp / name).write_text(text)
    for name in files:
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp / name, dest / name)
    shutil.rmtree(tmp, ignore_errors=True)


def _dump(x: Any) -> str:
    return json.dumps(x, indent=2, sort_keys=True) + "\n"


def _jsonl(rows: list[Any]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def bundle_files(doc: dict[str, Any]) -> dict[str, str]:
    """The export document → {relative path: text}, per docs/EVOLUTION-DESIGN.md §6."""
    files = {"lineage.json": _dump(doc.get("lineage", {}))}
    for agent, versions in sorted((doc.get("playbooks") or {}).items()):
        for v in versions:
            files[f"playbooks/{agent}-v{v.get('version')}.json"] = _dump(v)
    for g in doc.get("generations", []):
        d = f"gen-{g.get('generation')}"
        files[f"{d}/episode.json"] = _dump(g.get("episode", {}))
        for part in ("events", "audit_log", "verdicts", "debriefs"):
            files[f"{d}/{part}.jsonl"] = _jsonl(g.get(part) or [])
        files[f"{d}/attacks.json"] = _dump(g.get("attacks") or [])
        files[f"{d}/score.json"] = _dump(g.get("score") or {})
        files[f"{d}/credits.json"] = _dump(g.get("credits") or {})
        for agent, versions in sorted((g.get("playbooks") or {}).items()):
            for v in versions:
                files[f"{d}/playbooks/{agent}-v{v.get('version')}.json"] = _dump(v)
    return files


def _load(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read {path}: {e}")


def main(argv: list[str]) -> None:
    ok = (len(argv) == 2 and argv[0] in ("report", "export")) or (len(argv) == 3 and argv[0] in ("report-file", "export-file"))
    if not ok or not ID.match(argv[1]):
        sys.exit(__doc__)
    cmd, ln = argv[0], argv[1]
    dest = Path(os.environ.get("RUNS_DIR", "runs")) / ln
    if cmd.startswith("report"):
        rep = get(f"/api/fe/lineages/{ln}/report") if cmd == "report" else _load(argv[2])
        _write_checked(dest, {"report.json": _dump(rep), "report.md": render_md(rep)})
        print(f"{dest}/report.md")
    else:
        files = bundle_files(get(f"/api/lineages/{ln}/export") if cmd == "export" else _load(argv[2]))
        _write_checked(dest, files)
        print(f"{dest}: {len(files)} files")


if __name__ == "__main__":
    main(sys.argv[1:])
