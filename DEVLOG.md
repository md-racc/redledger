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
- 2026-10-24T01:51Z · Al · red: bank_swap + duplicate_invoice schemes (PR 1 of 2), ghost_vendor default moved under the near_threshold band, Droid SDK + uv-workspace findings in contracts/CHANGELOG; verified 3-day DRY_RUN episode on real red container vs mock green/blue; next: threshold_split + ghost_employee PR, then expense_inflation/po_mismatch/amount_drift; blocked: make test-red fails until Ad fixes uv workspace sources
- 2026-10-24T02:17Z · Ad · frontend: server-side /api/bf proxy holds OPERATOR_TOKEN, ws via 60 s tickets, no tokens/URLs in NEXT_PUBLIC_*, lockfile committed (unblocks CI npm ci), .dockerignore; for R to review; next: e2e against env-tokens stack; blocked: battlefield/env-tokens for /ws/ticket
- 2026-10-24T02:41Z · Ad · contracts: AGENT_TOKEN/OPERATOR_TOKEN split (INTERNAL_TOKEN fallback), POST /ws/ticket + /ws ticket auth (4401), GET /events operator-only, credit_guard error; fixed unparseable /state YAML; affected: all — tag Al M R; next: battlefield/env-tokens implements it; blocked: none
- 2026-10-24T02:45Z · Ad · battlefield: AGENT_TOKEN/OPERATOR_TOKEN enforced by role (INTERNAL_TOKEN fallback), GET /events operator-only, single-use 60 s ws tickets (4401 on failure), per-episode credit guard (MAX_CREDITS_PER_EPISODE), prod .env rendered from GitHub production env, deploy gated by DEPLOY_ENABLED, no build-time secrets; fixed agent narration events 400 (missing X-Tool-Use-Id) since scaffold; next: frontend proxy + docs; blocked: none
- 2026-10-24T02:53Z · Al · battlefield: agentkit live-Droid fixes (tools run off the SDK loop, events send X-Tool-Use-Id, restrict_tools uses <server>___<tool> IDs, DROID_REASONING_* knob); proven with live red on gemini-3.8-flash: 2 days, 1,004 extracted, 14s/79s turns; next: Ad review + merge, then green/blue live; blocked: none
- 2026-10-24T01:52Z · Al · red: threshold_split + ghost_employee schemes (PR 2 of 2, stacked on red/schemes-bank-swap-dup); catalog now 5 schemes; next: expense_inflation/po_mismatch/amount_drift + adaptive selection from blocked statuses; blocked: none
- 2026-10-24T02:51Z · Al · red: live turn prompt (catalog inlined, one inspect + one run_scheme, then stop); first live red runs on gemini-3.8-flash: 2 days, 2 bank_swaps, 1,004 extracted, 14s/79s turns, ~6.7k Factory credits/turn; needs Ad's agentkit fix (tools stall on await, events 400, restrict_tools IDs) to run live; next: expense_inflation/po_mismatch/amount_drift; blocked: agentkit patch
- 2026-10-24T03:00Z · M · green: add isolated clerk primitives and HTTP fixtures with Decimal, turn-scope and procedural-operation tests (part 1/3); existing agent unchanged; next: activate AP workflow; blocked: shared live preflight/identity protocol
