# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T01:44Z · Ad · chore: drop root uv workspace pyproject (broke per-service uv sync, so CI python failed everywhere); next: battlefield tests + scoring fixes; blocked: none
- 2026-10-24T02:05Z · Ad · chore: real CODEOWNERS handles (Al=Alex-Epstein, M=moterodiaz, R=RaagaSundar, Ad=md-racc) with backup owners so self-authored PRs stay mergeable under admin-enforced protection; next: branch protection on main; blocked: none
