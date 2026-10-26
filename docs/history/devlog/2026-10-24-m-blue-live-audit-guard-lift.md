## 2026-10-24 — M — blue: lift the live-audit guard on merged evidence

Retired the `_droid_turn` hard stop and the six `LIVE_BLOCKERS`; live readiness is now gated
only on SDK availability. Each blocker maps to merged evidence (happy + interrupted real-Ledger
sessions, `ep_edd0d922b9a5` / `ep_677e52f4197f`); the mapping table and surviving operational
notes (gpt-5.4-mini, 170 s budget cap, stall-as-partial) live in `blue/SDK-READINESS.md`.
