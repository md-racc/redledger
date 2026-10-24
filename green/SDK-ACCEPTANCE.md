# Green SDK acceptance proposal

Status: **not executed or authorized**. Canonical stack: #93 → #94 only.
OFF, explicit strict identity, and the production pre-SDK guard stay in place.
Ad owns merging, deployment, seed/episode setup and the three-day all-real shadow checkpoint.
No parallel handler integration, CRS/provider requests or Bright Data use.

## Established evidence

Merged Finding #96 and [the portable #94 reproducer](https://github.com/md-racc/redledger/pull/94#issuecomment-6386862610)
observed nine AP IDs on SDK 0.5.0 / MCP 1.30.0 with zero streams or tool/Ledger calls.
#94 pins that immutable list before the first Session and returns fresh expected-ID lists.
Keyless configuration and mocked HTTP tests are not SDK restriction or real Ledger evidence.

## Proposed budget, requiring explicit approval before any stream

- Maximum **16 fresh Sessions / 16 model streams**, serial, one attempt per case.
- Maximum **45 seconds per Stage A Session**, **135 seconds per Stage B Session**,
  including opening/closing: **18 minutes aggregate**. Reject a hold/HTTP budget plus
  cleanup margin that cannot fit; never shorten the configured escalation to pass.
- Proposed **50,000 Factory credits total**, model `gemini-3.8-flash`, reasoning `low`.
  This is a proposed ceiling, not a price estimate or authorization.
- Require an enforceable service-side spend cap before starting, or explicit approval of
  the possible one-in-flight overrun. Post-stream usage alone cannot enforce a hard credit cap.
  Record/debit every usage result; missing usage or insufficient remaining budget stops the run.
- No retries, auth/model guessing, fallback paid probes or automatic budget replenishment.
  Stop on the first failed/inconclusive row, unexpected/repeated execution, timeout or unknown ID.
  Explicit approval is required for any resumed attempt, new model or larger budget.

## Matrix and evidence boundaries

| Stage | Streams | Required observations |
|---|---:|---|
| A: SDK + intercepted Ledger HTTP | 9 | One targeted call per AP tool under OFF, including read-only `ap_queue`; permission arrives before execution, uses one SDK ID, and only `PROCEED_ONCE` allows it. |
| A: cancellation | 1 | Canonical block returns CANCEL; a nonce supplied only in the comment reaches subsequent model text; one false narration pair and zero execution writes. |
| A: granularity | 1 | Request two tools; record actual action/use cardinality. A multi-use callback must cancel before any preparation, never partly authorize the batch. |
| A: restriction | 1 | First Session uses exactly the pins with built-ins disabled; an attempted unlisted tool never executes. Listing alone is insufficient proof. |
| B: real isolated Ledger | 4 | Off allow, shadow would-block/effective-allow, enforce block, and enforce escalation timeout; verify persisted preparation/consumption and actual gate/write counts. |

Stage A uses real SDK callbacks with synthetic books and intercepted HTTP: **no real Ledger commits**.
For each mutation, correlate permission → preparation header → first execution header → event pair;
each request uses the same SDK ID, one preparation at most, and no duplicate execution.
`ap_queue` must never prepare. No generated live identities or direct Green → Blue traffic.
Stage B needs Ad-provided isolated fixtures and an active turn; only LedgerClient is agent-facing.
Ad's out-of-band operator evidence, never an agent scoreboard/event-read tool, checks at most
one gate per prepared action (off may bypass Blue), one allow commit, zero block/timeout writes,
and no gate replay on consume.
Keep SDK comments, AP summaries and integration failures distinct from controller holds.

Use a separately reviewed acceptance-only harness, never a production guard change; empty temporary
Session cwd, configured CLI auth, `_env_file=None`, and no secret/session payload logging.
Record exact SHAs/versions/model, row outcome, sanitized IDs/counts and credits; fail or mark
inconclusive when any link is absent. No result is currently claimed for this matrix.
Only a complete reviewed matrix can support a separate guard-lift request. It cannot authorize
deployment or replace Ad's three-day all-three-real-agent shadow evidence for Phase C.
