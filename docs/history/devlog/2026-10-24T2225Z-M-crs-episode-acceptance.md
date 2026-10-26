# 2026-10-24T2225Z — M — CRS episode acceptance driver + battlefield flags-context finding

blue: added `blue/tests/crs_episode_acceptance.py` (opt-in, `--allow-provider-call`), the
episode-level CRS acceptance driver: fixture P01/P12/P16 employees + expenses via the merged
operator route, operator-bind, stepped two-day enforce episode with the keyless audit on
`CRS_LIVE=true`. Live run ep_e1d35dfb24b1: exactly one high employee flag (P12 mismatch),
P01/P16 neutral, day-0 expenses paid, 2 reports, provider logs 13 identity checks all
`billable:false`. Found a battlefield gap: `_expense_context` never includes `flags`, so
`already_flagged_high` cannot fire on expense actions; reported on #102 with the fix.
