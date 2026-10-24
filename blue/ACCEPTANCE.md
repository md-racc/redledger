# Remaining Blue acceptance

Code and offline verification are not live acceptance. Blue/M owns its adapter and isolated
SDK proof; Ad supplies the coordinated runtime. Keep the runtime hard stop and false readiness
until the required evidence exists. Do not change Green's active PRs or enable Bright Data.

## Authenticated SDK, real Ledger, and concurrent gate

1. With explicit model-spending approval, use the portable command in
   [SDK-READINESS.md](SDK-READINESS.md#controlled-authenticated-sdk-checkpoint).
   Record the source SHA, CLI/SDK/MCP/model versions, sanitized JSON and usage. A zero-callback
   or zero-write run is inconclusive; diagnose its fixed failure codes before another attempt.
2. Controlled success is only intercepted HTTP. Under Ad's coordinated sandbox, separately
   prove a real Ledger commit and receipt linked to the SDK permission/event ID, exactly one
   event pair, no duplicate execution, and truthful interrupted/unknown receipt handling.
3. Ad + M must qualify concurrent `/gate` against the actual running Blue audit, below eight
   seconds. The portable probe's local ASGI timing is not production evidence.
4. Only after owner acceptance and independent verification, implement any guard/readiness
   change in a separate reviewed PR. Ad owns deployment and the README §14 three-day
   all-real shadow run after Green and Blue qualify. CRS acceptance remains separate.

## Learned controls, PR #83

The reviewed branch was resynced with shared/strict adapters at `3617e3f`. Do not rewrite that
published history or mark it ready based only on its passing unit suite. Seeded acceptance
remains unrun here because Docker/Postgres are unavailable.

- Use one operator-coordinated stack. Pin the baseline and #83 candidate SHAs. Run the real
  Blue service in keyless mode, not mock Blue: the mock has its own learned-rule implementation.
  Keep gate LLM and sponsor calls disabled. Do not reset an existing database or start a
  second stack.
- Compare baseline and candidate on two seeds, with matching mode, days, Red/Green settings
  and attack scenarios. Exercise a lineage with an authorized after-action review and a later
  generation using the resulting exact Blue playbook version. A plain episode with no
  learned playbook does not exercise #83.
- Existing operator commands in [README §15](../README.md#15-evolution-runs-lineages) include:

  ```sh
  make evolve GENS=2 DAYS=6 MODE=enforce SEED=42 REVEAL_DAYS=3 REVEAL_GENERATIONS=2
  make lineage-status LN=<returned-lineage-id>
  make evolution-report LN=<returned-lineage-id>
  ```

  Finish one lineage before the next; repeat the comparison with base seed 43. Record actual
  episode seeds, learned rule IDs, playbook versions, ledger outcomes and per-rule/confusion
  metrics. Match scenarios before attributing score differences to learned controls.
- Check legitimate holds, false-positive cost, prevented losses, baseline holds, and the
  retirement of learned rules after legitimate impact. If no learned rule is exercised, record
  missing coverage rather than a pass. Send sanitized evidence to Ad; keep ground-truth
  exports under ignored `runs/`, never in agent prompts or committed fixtures.

These seeded checks do not satisfy authenticated audit, CRS, or the all-real shadow checkpoint.
