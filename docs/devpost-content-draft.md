# Devpost content: first draft

Status as of 2026-10-25 ~04:45Z, main @ 53adcb7; prod @ fb829e6. The draft for the Cal Hacks 13.0 Devpost fields, ready to paste. The
claims come from the per-track docs in [`devpost/`](devpost/README.md), where each number and status has a
source. Before submitting, re-check anything marked live against what's true on the day. Sentences that depend on a
planned item (P8–P9, see [`devpost/README.md`](devpost/README.md)) are marked `[only if P#]`: delete the marker if it
landed, or the sentence if it didn't.

---

## Elevator pitch

Devpost's limit is 200 characters. This one is 158.

```
A crash-test lab for finance AI: a live fraud agent attacks a synthetic company while an AP agent pays its bills and a controller agent decides every payment.
```

Alternative:

```
Would you let an AI pay your company's bills while someone tries to trick it? We built the lab that finds out, and scores the answer in dollars.
```

---

## About the project

Devpost renders markdown. Paste the block below as-is.

```markdown
## Inspiration
Finance teams are being asked to let AI agents pay bills. In accounts payable the expensive failures aren't typos. They're fraud: a vendor's bank details "updated" the day before a payment run, a vendor that didn't exist last week, an invoice split to land just under the approval limit. Before a car goes on the road, you crash it. Before an AI touches your money, you just hope. Nobody tests an AP agent against someone actively trying to trick it, so we built the test.

## What it does
Red Ledger runs a synthetic company, Coastal Supply Co. (60 vendors, 40 employees, 90 days of paid history), through simulated business days. Three agents share one ledger:

- **Green, the AP clerk**, matches invoices to purchase orders, pays bills, approves vendor bank changes and reimburses expenses.
- **Blue, the controller**, decides each of those actions before it happens: allow, block, or escalate to a human, with rule IDs and a plain-English reason. Once a day it also audits the books as a live agent on Factory's Droid SDK, flags and freezes suspicious vendors, and posts a report. Its audit can also check operator-bound new hires against TransUnion identity verification through the CRS sandbox (proven from our local stack).
- **Red, the fraud agent**, runs live on Factory's Droid SDK. It reads the books like an insider and picks from eight schemes: ghost vendors, bank-account swaps, duplicate invoices, threshold splits, ghost employees, inflated expenses, invoices over their purchase order, and creeping recurring amounts. It uses only the access a junior insider would have.

A judge can steer the attack: type or say a fraud scheme in your own words, in any language. Red gets the words as quoted data and uses them to choose its scheme or tune it, but it can only ever run its own catalog.

An escalation waits up to 90 seconds for a person. If nobody answers, the action is blocked. Every call lands in an audit log. A scoreboard tracks dollars extracted, dollars blocked, detection latency, and what false positives cost, so blocking everything loses too.

Agents also **evolve**. Across generations of episodes, each agent gets debriefs on what was caught and rewrites a versioned playbook.

**Results on our production deployment** (recorded with red live; green and blue ran keyless at the time):
- Same company, same seed, 10 days: controller off, **$10,285** stolen. Controller on, **$1,824** stolen, at $100 of false-positive cost.
- Over a 5-generation evolution run, the live attacker found that invoices split under the approval threshold get paid, and leaned on it harder every generation: 1 of 7 attacks in generation 1, 7 of 8 in generation 5, with extraction rising from $19k to $98k. No control caught it. The lab surfaced a real control gap, which is exactly what you'd want to learn before hiring the agent. `[only if P9]` After we added an invoice split control, a short live re-run showed the controller closing it.
- Against the live CRS sandbox (from our local stack), a new hire whose identity didn't check out was flagged by the controller's audit, and their next expense was blocked at the gate. The two clean identities were paid. Every sandbox call was non-billable.

## How we built it
Five services plus Postgres, deployed on a Vultr VM behind Cloudflare. The live site is public and read-only: anyone can watch, and only our admin laptops can start runs or launch attacks, enforced on the server. Only one service, `battlefield` (FastAPI), touches the database. It is the Ledger API, the clock, the gatekeeper and the scorekeeper. Agents reach it only over HTTP, with per-agent tokens and per-route permissions. Ground truth (which rows are fraud) lives in a hidden column stripped from every agent response, so scoring is honest.

Before green moves money it calls `POST /preparations`. Battlefield asks blue, stores the verdict, holds any escalation, and binds the decision to the exact action plus a fingerprint of the vendor's bank details, so a bank change in between invalidates the approval. Blue's gate is a deterministic rules engine (vendor age, near-threshold, duplicates, recent bank changes, PO ceilings, recurring-amount drift, same-day expense splits, HR checks, holds) with an optional LLM that can only advise, never decide. Blue's daily audit is a Droid agent that works only through service-validated findings: it can raise a flag or freeze a vendor only by a finding ID the service produced. One of its tools logs in to the CRS sandbox and checks operator-bound fictional personas; a mismatch becomes a high-severity hold that the gate enforces on the next payout.

All three agents share one `agentkit` package around Factory's Droid SDK. Each has a custom system prompt, Droid's built-in skills switched off, and an in-process MCP server exposing only its own ledger tools. Droid's tool-call ID becomes the ledger's idempotency key. Red and blue's audit run live on it; green, the clerk, runs the same harness without model calls. The frontend is Next.js with a 3D arena plus a backstage console per team, all fed from one event stream, and an attack console that takes typed or spoken requests (speech-to-text by ElevenLabs). Every episode can be recorded and replayed.

## Challenges we ran into
- **Making "ask first" airtight.** A verdict has to be bound to the exact action. That took idempotency keys bound to their first action, a state fingerprint recomputed inside the payment transaction, and compare-and-set status changes, so two parallel pay calls can't produce two payments.
- **Escalations had to resolve exactly once** across a human click, a timeout and a server restart.
- **Hiding ground truth while still letting agents learn** needed its own disclosure policy: only resolved attacks, inside a sliding window, every disclosure logged.
- **On the live side,** one model stalled red's turns until our 170-second timeout. We measured credits per turn and switched models, for red and for blue's audit.
- **Red-teaming our own range,** we found the attacker could read its attack outcomes before its debrief revealed them, and a stored gate verdict could be replayed on a later day or after a switch to enforcement. We closed both.
- **Our first CRS run** showed the identity flag landing but never reaching the expense gate. We fixed the gate's evidence and re-ran it against the live sandbox until the block fired.

## Accomplishments that we're proud of
- The controller fails closed: a timeout blocks, and an unreachable controller or missing evidence escalates.
- False positives are real, because the company generates legitimate bank changes and new vendors every few days.
- Two agents run live on Factory's Droid SDK: the fraud agent at about 11 seconds and ~2.6k credits per turn, and the controller's daily audit at about 4k credits a day.
- Every decision traces from a rule ID to a written reason to an audit row.
- The lab found a genuine gap in its own controls.

## What we learned
Most of autonomous AP is deciding what *not* to touch: defer over-limit invoices, defer invoices with no PO, never retry a blocked action. A good controller is one a human can argue with, so it gives reasons, not a score. And the fair way to grade a controller is in dollars on both sides: what it stopped, and what it cost.

## What's next
Close the gap the live run found. The expense version of the split control is shipped; the invoice version is next `[only if P8: "and shipped"]`, then a re-run of the lineage to show it holds `[only if P9: "which showed it holding"]`. Put green, the clerk, on a live Droid session after its acceptance run. Add three-way match (receiving) and approval routing above the threshold.
```

---

## Built with

25 tags, all used in the repo. New since the first draft: `elevenlabs` (voice attack console, #154/#162) and `crs-api` (blue's CRS identity check). Dropped to stay at 25: `docker-compose` (covered by `docker`) and `uv` (dev tooling).

```
python, fastapi, pydantic, httpx, asyncpg, postgresql, timescaledb, factory-droid-sdk, mcp, gpt-5.4-mini, next.js, react, typescript, tailwindcss, three.js, react-three-fiber, websockets, docker, caddy, cloudflare, vultr, github-actions, pytest, elevenlabs, crs-api
```

If Devpost's autocomplete prefers its own names, swap in `openai` for `gpt-5.4-mini` and `nextjs` for `next.js`. Devpost accepts free-text tags, but if it suggests a sponsor tag for CRS, use that instead of `crs-api`. If voice isn't working on prod by submission, swap `elevenlabs` back to `uv`.

---

## "Did you implement a generative AI model or API in your hack this weekend?"

**Yes.**

```
Yes. Two of our three agents run live in production on Factory's Droid SDK, on gpt-5.4-mini.

Red, the fraud agent (reasoning: low), reads the company's books each turn through an in-process MCP server limited to red's own Ledger API tools, chooses one of eight fraud schemes that blends in, and executes it, at about 11 seconds and ~2.6k Factory credits per turn. A judge's own words, typed or spoken, are passed to it as quoted data to steer the scheme or its parameters. Between generations it receives debriefs and its playbook is updated.

Blue, the controller, runs its daily audit as a live Droid agent: it reviews the day's service-derived facts, calls its audit tools, raises flags or freezes vendors only through findings the service validated, and posts a report, at about 4k credits per audit. Blue's per-payment gate is deterministic rules; it also supports an optional LLM advisor (Gemini, Anthropic or OpenAI) that can only add advice, never decide, and that advisor is off in production.

Green, the AP clerk, is built on the same Droid SDK harness but runs its procedure without model calls in production, by our choice for the demo.

We tested gemini-3.8-flash and switched away after it stalled live turns. The attack console transcribes speech with ElevenLabs speech-to-text. The hack also calls an external, non-generative API: the CRS sandbox (TransUnion identity verification), which blue uses to check new hires against fictional test personas.
```

Optional, the team's call: *"We also used Claude Code (AI coding agents) heavily during development."* It's true of how this repo was built.

---

## Before submitting

- **The 90-second arena show replays a recording on prod**, because red is live. If the video uses it, label it "recorded on our production deployment". The live proof is Launch attack plus the backstage consoles.
- **Live status:** red and blue's audit are live, green is keyless by decision (#78). Don't write "three live agents".
- **Voice:** #154 was never tested against the real ElevenLabs service. Record one real transcription on prod before submitting. If it fails, remove the "or say" wording and the ElevenLabs sentences, and swap the tag.
- **CRS:** the About text says "from our local stack" on purpose. Keep it unless CRS runs on prod. Submitting to the CRS track needs the live table demo (devpost/crs.md §0).
- **`[only if P#]` markers:** resolve each one (P8 invoice split control, P9 re-run) against devpost/README.md before pasting.
- **Sources for the numbers:**
  - off/on recordings: [`docs/recordings/README.md`](recordings/README.md) (#136)
  - 5-generation live-red lineage `ln_f52a3df83c8d` and red's per-turn cost: [`devpost/factory.md`](devpost/factory.md) and [`devpost/hyphenate.md`](devpost/hyphenate.md) §10
  - blue's live audit credits (3,806 and 4,109, ep_f9c695b3144f): #78; [`devpost/factory.md`](devpost/factory.md) §10
  - CRS acceptance (ep_0181eda1c921, 19 checks `billable:false`): #102; [`devpost/crs.md`](devpost/crs.md) §0
  - false-positive cost formula: README §4
- **Website / "Try it out" link:** `https://app.redledger.us`. It is public and read-only (P7, live), so judges can open it on their own devices and watch; only the stage laptops signed in at `/admin` can start runs, launch attacks, use voice or resolve escalations.
