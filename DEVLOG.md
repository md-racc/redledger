# DEVLOG — the common ledger

Append-only. One line per PR or working session. Newest at the bottom. Never edit another
person's line. `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"`.

Findings about SDKs and sponsor APIs belong in `contracts/CHANGELOG.md` under Findings; link
them from here.

---

- 2026-10-23T00:00Z · Ad · repo scaffolded: contracts, agentkit, battlefield (ledger API, gate, orchestrator, scoring, mock agents), skeletons for red/green/blue/frontend; next: hosting decision + first live episode on mock agents; blocked: none
- 2026-10-24T01:51Z · Al · red: bank_swap + duplicate_invoice schemes (PR 1 of 2), ghost_vendor default moved under the near_threshold band, Droid SDK + uv-workspace findings in contracts/CHANGELOG; verified 3-day DRY_RUN episode on real red container vs mock green/blue; next: threshold_split + ghost_employee PR, then expense_inflation/po_mismatch/amount_drift; blocked: make test-red fails until Ad fixes uv workspace sources
- 2026-10-24T01:52Z · Al · red: threshold_split + ghost_employee schemes (PR 2 of 2, stacked on red/schemes-bank-swap-dup); catalog now 5 schemes; next: expense_inflation/po_mismatch/amount_drift + adaptive selection from blocked statuses; blocked: none
