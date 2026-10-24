# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

**Entries after 2026-10-24T03:00Z live in `devlog/`, one file per PR** (`make devlog WHO=… MSG="…"`
writes it; `GIT.md` §6). `make devlog-show` prints this history plus every fragment, sorted by
time. The lines below are frozen history: don't append here, don't edit or reorder them.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T01:45Z · Ad · docs: AGENTS.md §3 invariant 11 — agents never read /events, /fe, operator routes, or each other's internals; blue reads audit_log for green/blue only; next: code-level filtering as a contracts PR; blocked: none
- 2026-10-24T02:31Z · Ad · docs: env + token docs (README §5/11/12/13/17, AGENTS invariants 9/12, per-team AGENTS lines, deploy/ENVIRONMENT.md); next: teammates add AGENT_TOKEN+OPERATOR_TOKEN to local .env; blocked: none
