# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T02:17Z · Ad · frontend: server-side /api/bf proxy holds OPERATOR_TOKEN, ws via 60 s tickets, no tokens/URLs in NEXT_PUBLIC_*, lockfile committed (unblocks CI npm ci), .dockerignore; for R to review; next: e2e against env-tokens stack; blocked: battlefield/env-tokens for /ws/ticket
