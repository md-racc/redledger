# Red lineage learning

Only valid `options.lineage` enables playbook reads/updates. Plain episodes keep their
prompt, deterministic rotation, and no playbook I/O. Forced scheme/parameters take priority.
The live prompt reads the own playbook and previews the debrief fold; `inspect_books`
re-reads the current version and persists new evidence inside its decorated invocation.
LedgerClient supplies its write ID (or `:n`), and the wrapper emits one event pair.
409/413/server errors never retry the write and never cost the attack: a failed playbook
read drops the learning section from the prompt, `inspect_books` still returns the books with
`lineage: {"error": <status>}`, and keyless turns fall back to the plain rotation.
On judge-forced scheme days learning persists only if the model calls `inspect_books`; the
sliding debrief window and the between-generation reflection cover any day it does not.
A missing playbook is neutral, not permission to guess a base version.

`red_evolution` version 1 retains at most 128 typed categorical observations, ordered by
generation/launch day/hashed episode+attack identity. Repeated sliding-window/AAR items
deduplicate; replayed evicted items cannot displace the retained window. Summaries count
only that bounded window. The most recent result per scheme determines preference:
undetected extraction, then untried schemes, then uncaught failures, then caught attempts.
A `failed` outcome counts as caught only with a detection or a blocking control. Day
rotation breaks ties. Later catches override earlier wins, not vice versa.

Only own attack disclosures are consumed. Daily unresolved/pending and unknown schemes
are ignored; ended reviews can disclose unresolved non-pending outcomes. Score, history
summaries, raw reasons/rules, entity IDs, prose, code, and arbitrary operator content are
never strategy instructions. Only outcome/detection and categorical control kinds survive.
Unrelated operator content is preserved in storage, not copied into prompts. Malformed or
oversized namespaces/content are kept unchanged and ignored; updates cap content at 60KB.
No events, scoreboard, reports, flags, opponent playbooks, database, or provider reads.

Both reflection hooks use the same pure fold and return content or null. They never call
the ledger; battlefield persists the version. Keyless turns use the existing tools and
run on the dedicated turn loop (`turn_loop_dry_run=True`). No composed schemes are added.

Validation: Python 3.11, `DRY_RUN=true .venv/bin/python -m pytest -q` in `red/`;
focused files `tests/test_evolution.py` and `tests/test_agent_evolution.py` cover bounded
memory, dedup, recency, malformed data, prompt/forced behavior, invocation header/event
parity, conflicts, pure reflection, and keyless `/turn` on the service factory.
Run root `make lint test-red TOKEN=test-operator` with `UV_NO_ENV_FILE=1 UV_NO_SYNC=1`
(dependencies already installed, no lockfile generation).

Evidence is keyless/unit/service-factory only, not a live lineage qualification. Red stays
HIGH with best-effort identity (SDK ID when linked, local fallback otherwise); D7 strict
Red remains an owner decision. No live SDK tool-ID, permission, provider, production,
budget, or end-to-end battlefield acceptance is claimed. Independent verification and
owner-approved capped live acceptance remain necessary before closing issue #77.
