# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T02:41Z · Ad · contracts: AGENT_TOKEN/OPERATOR_TOKEN split (INTERNAL_TOKEN fallback), POST /ws/ticket + /ws ticket auth (4401), GET /events operator-only, credit_guard error; fixed unparseable /state YAML; affected: all — tag Al M R; next: battlefield/env-tokens implements it; blocked: none
