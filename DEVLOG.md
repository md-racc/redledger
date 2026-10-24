# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T01:44Z · Ad · chore: drop root uv workspace pyproject (broke per-service uv sync, so CI python failed everywhere); next: battlefield tests + scoring fixes; blocked: none
- 2026-10-24T02:05Z · Ad · chore: real CODEOWNERS handles (Al=Alex-Epstein, M=moterodiaz, R=RaagaSundar, Ad=md-racc) with backup owners so self-authored PRs stay mergeable under admin-enforced protection; next: branch protection on main; blocked: none
- 2026-10-24T02:17Z · Ad · battlefield: first battlefield tests (unit + DB tier, Postgres in CI), PYTHONPATH for service tests, deploy/ in ownership guard; scoring credits bank_swap (blocked at approve or at pay time), bounds swap windows, no pre-launch detection, FP excludes controller-correct blocks; smoke enforce 4/4 caught $0 extracted; next: env-tokens; blocked: none
- 2026-10-24T02:51Z · Al · red: live turn prompt (catalog inlined, one inspect + one run_scheme, then stop); first live red runs on gemini-3.8-flash: 2 days, 2 bank_swaps, 1,004 extracted, 14s/79s turns, ~6.7k Factory credits/turn; needs Ad's agentkit fix (tools stall on await, events 400, restrict_tools IDs) to run live; next: expense_inflation/po_mismatch/amount_drift; blocked: agentkit patch
