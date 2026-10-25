# Sponsors: what we used, how, and the proof

For every prize we enter: the **features of the sponsor's product that we use**, where a judge sees each one in the demo, the proof in the repo, and the honest status. The spoken lines are in [pitch-script.md](pitch-script.md) (sponsor names in **bold**). The long evidence per track is in [`docs/devpost/`](../../docs/devpost/README.md); the prize rules and what to drop are in [`INTEGRATIONS.md`](../../INTEGRATIONS.md) §5. Nothing here claims more than that ledger does.

Status words (the ledger's): **LIVE** = running on prod with a real model today; **ON MAIN** = merged and tested, keyless or CI-proven, not exercised live on prod.

## Factory: Best Use of the Droid SDK ($2,000 + credits)

| Droid SDK feature | How we use it | You see it |
|---|---|---|
| General agent runtime, not a coding tool | a string `system_prompt` per agent (replaces the coding prompt), `disable_builtin_skills=True` | red and blue's audit are non-coding agents |
| `restrict_tools` with exact ids | each agent holds only its own `<agent>-ledger___<tool>` ids | red can submit invoices and nothing else |
| In-process MCP tools | one `tool()` per ledger function, over the Ledger API | the tool tape on `/backstage/red` |
| **Autonomy as a trust dial** | red at `HIGH` (never asked); blue's audit at `OFF` (every tool call is a permission request, answered `PROCEED_ONCE`) | "nobody asks me permission" vs "every tool call I make is a permission request" |
| Tool-call id as the idempotency key | the id the SDK reports becomes `X-Tool-Use-Id`; strict mode refuses any call it cannot match | no action runs twice |
| Streaming | `ThinkingDelta` becomes `agent.thinking` | red's reasoning streaming onto laptop 2 |
| Usage | `factory_credits` per turn, summed against per-episode and per-lineage caps | credits on `turn.ended` |

Status: red **LIVE** (`gpt-5.4-mini`); blue's daily audit **LIVE** (#157); green **ON MAIN**, keyless by Ad's decision (#78). **Say** "red and blue live on Droid; green on the same harness, keyless", never that green runs live. Proof: `agentkit/agentkit/droid_agent.py`, README §6 "Where Droid runs", [factory.md](../../docs/devpost/factory.md).

## Hyphenate: Autonomous Systems for Finance ($8k / $5k / $3k)

| What the judges want | Where it is |
|---|---|
| Realistic data | a seeded company: 60 vendors, 40 employees, 90 days of history, and legitimate bank changes and new vendors so the controls can be wrong |
| Limited access | only battlefield touches the database; per-agent tokens; red cannot pay or approve |
| A clean record | every call writes `audit_log`; every gate decision is a verdict row and event |
| Knowing when to ask | blue escalates a bank change; a human decides; nobody answering in 90 s is a block |
| Something new | a live attacker, and agents that rewrite their playbooks across generations |
| The moment | the bank swap at the gate (Your decision card) |
| Would you hire it | "Not today. Not without proof." Then the real run: about $10k lost without a controller, about $1.8k with one |

Proof: [hyphenate.md](../../docs/devpost/hyphenate.md). Real blue **does not** stop every attack (a split under the limit gets through); say so.

## Tiger Data (MLH Best Use)

`events` and `audit_log` are TimescaleDB hypertables keyed `(id, ts)`; score over time is a `score_timeline` **continuous aggregate** (one-minute buckets of `score.updated` per episode, real-time). CI runs the whole battlefield suite on `timescale/timescaledb:latest-pg16`. Status: **ON MAIN**, CI-proven. **Production runs plain Postgres 16**: never say "in production". Proof: `battlefield/app/timescale.py`, #98, #100.

## Vultr (MLH Best Use)

The whole stack runs on one Vultr VM, deployed by an approval-gated GitHub Actions workflow (README §13, §17). **LIVE.**

## Microsoft (Built for the Real World, Customer Impact) and Cal Hacks Most Technically Advanced

One enforcement API with compare-and-set commits, so parallel tool calls cannot pay an invoice twice; verdicts prepared ahead, bound to a state fingerprint and claimed exactly once; crash recovery that pauses and expires held decisions; an approval-gated deploy that renders secrets on the server; an origin that only answers Cloudflare and verifies the Access token; a browser that never holds a credential; a public read-only site where only a checked admin can act; credit guards; replayable recordings. **LIVE** (infrastructure). Proof: [technical.md](../../docs/devpost/technical.md).

## Armadin: Best Security Hack

A real LLM attacker (**LIVE**) with eight schemes tuned to slip under specific rules, inside a range it cannot cheat: attack surface enforced by route allowlists, the answer key (`origin`) stripped from every agent response, damage scored server-side so red cannot grade itself, per-agent tokens against impersonation, and fourteen integrity and leak bugs caught by independent verifiers before merge. The honest gap the live lineage found: splits under the approval limit get past the gate. Criteria were still pending; re-check the Devpost page. Proof: [armadin.md](../../docs/devpost/armadin.md).

## ElevenLabs

Speech-to-text (`scribe_v2`) behind an admin-only server route; the language is detected, not chosen; the key never reaches the browser (`frontend/docs/voice.md`). Status: **ON MAIN**, key wired in the deploy (#162, #163). **The ledger says it was never tested against the real service**: record one real transcription on prod before you say it on stage; if it fails, use a Try chip and leave the sentence out. INTEGRATIONS lists no ElevenLabs prize: name it in the Devpost text and tags.

## CRS: Best Identity / Fraud Innovation (and Most Unexpected Use)

Blue's audit checks synthetic employees' identities against the CRS sandbox; a mismatch raises a flag that blocks that employee's next expense (`already_flagged_high`). Proven against the live sandbox from a local stack (ep_0181eda1c921, 19 checks, all `billable:false`); **no CRS call has run on prod**. The challenge's only rule is to show it working live, so this is a separate table demo, not part of the pitch. Proof: [crs.md](../../docs/devpost/crs.md).

## MLH Best Use of Gen AI

Live red and live blue-audit Droid agents, agents that evolve across generations, and a voice-or-text console whose words steer red. One line, same evidence as above.

## Not claimed

- **MLH Gemini**: red moved off `gemini-3.8-flash` after it stalled live turns; the gate LLM is off on prod. Drop it.
- **Figma**: nothing here was made in Figma.
- **Anthropic, GoDaddy, .Tech, Cartesia**: not submitted or not built.
