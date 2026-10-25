# Devpost content: first draft

Status as of 2026-10-24 ~23:40Z. The first draft for the Cal Hacks 13.0 Devpost fields, ready to paste. The
claims come from the per-track docs in [`devpost/`](devpost/README.md), where each number and status has a
source. Before submitting, re-check anything marked live against what's true on the day.

---

## Elevator pitch

Devpost's limit is 200 characters. This one is 166.

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
- **Blue, the controller**, decides each of those actions before it happens: allow, block, or escalate to a human, with rule IDs and a plain-English reason. Once a day it also audits the books, flags and freezes suspicious vendors, and posts a report.
- **Red, the fraud agent**, runs live on Factory's Droid SDK. It reads the books like an insider and runs ghost vendors, bank-account swaps, duplicate invoices, threshold splits and ghost employees, using only the access a junior insider would have.

An escalation waits up to 90 seconds for a person. If nobody answers, the action is blocked. Every call lands in an audit log. A scoreboard tracks dollars extracted, dollars blocked, detection latency, and what false positives cost, so blocking everything loses too.

Agents also **evolve**. Across generations of episodes, each agent gets debriefs on what was caught and rewrites a versioned playbook.

**Results on our production deployment** (recorded with red live and green and blue running their full logic keyless; blue's daily audit has since gone live, green stays keyless):
- Same company, same seed, 10 days: controller off, **$10,285** stolen. Controller on, **$1,824** stolen, at $100 of false-positive cost.
- Over a 5-generation evolution run, the live attacker found that invoices split under the approval threshold get paid, and leaned on it harder every generation: 1 of 7 attacks in generation 1, 7 of 8 in generation 5, with extraction rising from $19k to $98k. No control caught it. The lab surfaced a real control gap, which is exactly what you'd want to learn before hiring the agent.

## How we built it
Five services plus Postgres, deployed on a Vultr VM behind Cloudflare. Only one service, `battlefield` (FastAPI), touches the database. It is the Ledger API, the clock, the gatekeeper and the scorekeeper. Agents reach it only over HTTP, with per-agent tokens and per-route permissions. Ground truth (which rows are fraud) lives in a hidden column stripped from every agent response, so scoring is honest.

Before green moves money it calls `POST /preparations`. Battlefield asks blue, stores the verdict, holds any escalation, and binds the decision to the exact action plus a fingerprint of the vendor's bank details, so a bank change in between invalidates the approval. Blue's gate is a deterministic rules engine (vendor age, near-threshold, duplicates, recent bank changes, PO ceilings, recurring-amount drift, HR checks) with an optional LLM that can only advise, never decide.

All three agents share one `agentkit` package around Factory's Droid SDK. Each has a custom system prompt, Droid's built-in skills switched off, and an in-process MCP server exposing only its own ledger tools. Droid's tool-call ID becomes the ledger's idempotency key. The frontend is Next.js with a 3D arena plus a backstage console per team, all fed from one event stream. Every episode can be recorded and replayed.

## Challenges we ran into
- **Making "ask first" airtight.** A verdict has to be bound to the exact action. That took idempotency keys bound to their first action, a state fingerprint recomputed inside the payment transaction, and compare-and-set status changes, so two parallel pay calls can't produce two payments.
- **Escalations had to resolve exactly once** across a human click, a timeout and a server restart.
- **Hiding ground truth while still letting agents learn** needed its own disclosure policy: only resolved attacks, inside a sliding window, every disclosure logged.
- **On the live side,** one model stalled red's turns until our 170-second timeout. We measured credits per turn and switched models.

## Accomplishments that we're proud of
- The controller fails closed: a timeout blocks, and an unreachable controller or missing evidence escalates.
- False positives are real, because the company generates legitimate bank changes and new vendors every few days.
- The fraud agent runs live at about 11 seconds and ~2.6k credits per turn.
- Every decision traces from a rule ID to a written reason to an audit row.
- The lab found a genuine gap in its own controls.

## What we learned
Most of autonomous AP is deciding what *not* to touch: defer over-limit invoices, defer invoices with no PO, never retry a blocked action. A good controller is one a human can argue with, so it gives reasons, not a score. And the fair way to grade a controller is in dollars on both sides: what it stopped, and what it cost.

## What's next
Close the gap the live run found: a per-vendor exposure control so split invoices stop slipping through, then re-run the lineage to show it holds. Put green on a live Droid session after its acceptance runs (blue's audit already runs live). Add three-way match (receiving), approval routing above the threshold, and the remaining fraud schemes.
```

---

## Built with

25 tags, all used in the repo.

```
python, fastapi, pydantic, httpx, asyncpg, postgresql, timescaledb, factory-droid-sdk, mcp, gpt-5.4-mini, next.js, react, typescript, tailwindcss, three.js, react-three-fiber, websockets, docker, docker-compose, caddy, cloudflare, vultr, github-actions, pytest, uv
```

If Devpost's autocomplete prefers its own names, swap in `openai` for `gpt-5.4-mini` and `nextjs` for `next.js`.

---

## "Did you implement a generative AI model or API in your hack this weekend?"

**Yes.**

```
Yes. Red, the fraud agent, is an LLM agent built on Factory's Droid SDK and runs live in production on gpt-5.4-mini (reasoning: low). Each turn, the model reads the company's books through an in-process MCP server limited to red's own Ledger API tools, chooses a fraud scheme that blends in, and executes it, at about 11 seconds and ~2.6k Factory credits per turn. Between generations it receives debriefs and its playbook is updated. We also tested gemini-3.8-flash and switched away after it stalled live turns.

Blue's daily audit (the controller's detective review) also runs live in production on the Droid SDK with gpt-5.4-mini: it reviews the day's books through its own restricted tools, raises flags, freezes vendors only where the service authorizes it, and posts a report, at about 4k Factory credits per audit. Green (AP clerk) is built on the same Droid SDK harness but runs its logic without model calls in production. Blue's payment gate also supports an optional LLM advisor (Gemini, Anthropic or OpenAI) that can only add advice, never decide. It is off in production.
```

Optional, the team's call: *"We also used Claude Code (AI coding agents) heavily during development."* It's true of how this repo was built.

---

## Before submitting

- **The 90-second arena show replays a recording on prod**, because red and blue are live. If the video uses it, label it "recorded on our production deployment". The live proof is Launch attack plus the backstage consoles.
- **Live status:** red and blue's daily audit are live on prod (blue since 2026-10-25); green stays keyless for the hackathon. Say "red and blue are live agents; green runs its full logic keyless" wherever the About text or the GenAI answer describes live status.
- **Sources for the numbers:**
  - off/on recordings: [`docs/recordings/README.md`](recordings/README.md) (#136)
  - 5-generation live-red lineage `ln_f52a3df83c8d` and red's per-turn cost: [`devpost/factory.md`](devpost/factory.md) and [`devpost/hyphenate.md`](devpost/hyphenate.md) §10
  - false-positive cost formula: README §4
- **Repo website link:** set it to the Devpost project URL once the project exists.
