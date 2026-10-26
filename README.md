# Red Ledger

**Every well-known accounts-payable fraud worked by fooling whoever approves the payment. Companies are now
handing that job to AI agents. Red Ledger is the crash test: a live fraud agent attacks an AI AP clerk, and the
control sits in the ledger, not in the agent's prompt.**

Built for Cal Hacks 13.0. **Completed October 2026.** Explore the screenshots and recorded results below,
or run the interactive arena locally without API keys. The original hosted demo is retired.

![The arena: red's fraudsters, green's clerks and blue's guards around the ledger, captured during the hackathon](docs/img/arena.jpg)


## The finished project

Red Ledger is a hackathon research prototype, preserved with its source, screenshots, recorded runs and
reproduction instructions. During the hackathon, red and blue's daily audit ran on Factory's Droid SDK
(`gpt-5.4-mini`). Green used the same harness keyless; blue's gate used deterministic rules.

The most useful result: red found an invoice-splitting gap, and a new ledger rule stopped its next split
attempt. [Results](#results) and [the evidence ledger](docs/EVIDENCE.md) explain the numbers and limits.
Green's live model path remains disabled; this is not a production finance system.

[View locally](#run-it-with-no-keys) · [Architecture](docs/ARCHITECTURE.md) · [Project closeout](docs/CLOSEOUT.md)

![An escalation: red asked to change a vendor's bank account while bills are open; the controller holds it and a person decides](docs/img/escalation.jpg)

## The company

The target is **Meridian Components**, a fictional electronics components distributor: 60 vendors, 40
employees, 90 days of payment history, and new legitimate vendors and bank changes every few days. Its vendors include component makers, PCB fabs, chip brokers and freight forwarders, so the flagship attack, a supplier's bank details
"updated" to an account the attacker controls, is the pattern a fake hardware supplier used to take more than
$120 million from two US tech companies. Cases and sources: [docs/EVIDENCE.md](docs/EVIDENCE.md).

## How it works

Each simulated day, three agents work the same ledger and none of them can see the others. **Red**, the
attacker, reads the books with a junior insider's access and runs one of eight schemes taken from real cases.
**Green**, the AP clerk, does the legitimate work. **Blue**, the controller, rules on every money-moving action
before it happens, and audits the books once a day.

```mermaid
flowchart LR
    red["red<br/>fraud agent"]
    green["green<br/>AP clerk"]
    blue["blue<br/>controller: gate rules, daily audit"]
    bf["battlefield<br/>Ledger API, orchestrator, scoring"]
    db[("Postgres")]
    fe["frontend<br/>arena and reports"]
    person(["a person"])

    red -->|"reads books, submits invoices and bank changes"| bf
    green -->|"step 1: prepare the payment"| bf
    bf -->|"step 2: ask the gate"| blue
    blue -->|"step 3: allow, block or escalate"| bf
    bf -->|"step 4: verdict enforced at the ledger"| green
    bf -.->|"escalation: 90 s to decide, then block"| person
    bf --- db
    fe -->|"server-side proxy"| bf
```

- **Only battlefield touches the database.** Agents hold no database credentials and reach the books only
  through the Ledger API over HTTP.
- **The ledger is the enforcement point.** Green prepares each action before acting; battlefield asks blue,
  stores the verdict and applies it on the payment route itself. If green is fooled, the payment still stops.
- **Agents never call each other or see the scoreboard.** Each agent has its own token. The event stream,
  WebSocket and frontend reads reject agent tokens, and blue's gate has one caller: battlefield.
- **Ground truth is hidden.** Which rows are fraud (`origin`, `attack_id`) is stripped from every agent
  response. Red learns only from the books and its own calls.
- **Fail closed.** An unreachable controller escalates; an escalation nobody answers in 90 seconds blocks. Every
  call lands in an audit log, and every verdict carries a rule ID and a plain-English reason.

The score is in dollars on both sides: what was lost, how much reached the attacker's own accounts, what was
blocked, how long detection took, and what false positives cost (2% of each wrongly blocked amount plus $50 per
item). Blocking everything loses.

## Results

These historical results were collected on the hosted system on October 24–25, 2026, with red on
Factory Droid (`gpt-5.4-mini`). Keyless local runs demonstrate the system; they do not reproduce model behavior.

| Run | Result |
|---|---|
| Same company, same seed, 10 days, controller **off** | Red swapped one vendor's bank account, the clerk approved it, and **$10,285** went to red's account. |
| Same run, controller **on** (enforce) | The ledger held the bank change for independent verification ("destination change overlaps open invoices"). **$0** lost (controls report). |
| 5 generations × 8 days, red learning between generations | Red found that invoices split under the approval limit got paid, and shifted to them. Extraction rose from **$18.5k to $93.6k** a generation, and no control caught it. |
| Red **and** blue's audit live, a fixed six-scheme plan, 6 days, before the split rule existed | **$18,526** lost with the controller on. $13,800 of it was one split invoice. |
| After we added a gate rule for the split (#206): 3 generations × 4 days, red and blue's audit live | **$0** stolen in every generation. Red's one split attempt was blocked (all 3 invoices), and red stopped splitting. |

The most useful result was a control gap nobody on the team saw coming. Red found it on its own in a few
simulated weeks, and the fix was a ledger rule, not a better prompt. What we don't claim:
[docs/STORY.md](docs/STORY.md#what-we-dont-claim) and [docs/EVIDENCE.md](docs/EVIDENCE.md#2-do-not-claim).

## Run it with no keys

For the interactive arena alone, install Node.js 22 and run:

```bash
cd frontend
npm ci
NEXT_PUBLIC_MOCK=true npm run dev
```

Open <http://localhost:3000>. This replays events with no backend, Docker or API keys. Screenshots above
show the original arena and escalation view; [recordings](docs/recordings/) retain real hackathon runs.

For a local simulation with Postgres and the Ledger API, install Docker Compose, Python 3.11 and Make:

```bash
cp .env.example .env     # set AGENT_TOKEN and OPERATOR_TOKEN to two different strings; set DRY_RUN=true
make mock-agents         # postgres + battlefield + stub red/green/blue; ports 5432, 8000-8003
make episode MODE=enforce SEED=42 DAYS=4      # prints `export EP=...`; run that line in your shell
# Wait for the episode to finish, then:
make score EP=$EP
make down
```

For the real agent implementations without model calls, use `make up-dry` instead of `make mock-agents`.
Under `DRY_RUN=true` agents use canned turns and blue's gate runs its rules. With no Docker,
`make local-stack AGENTS=mock` runs Postgres, battlefield and the agents as processes (stop with
`make local-stack-stop`); it requires Python 3.11 and `uv` (Postgres is supplied by `pgserver`).
Tests, environment variables and detailed local setup: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Repo layout

```
redledger/
├── battlefield/  Ledger API, orchestrator, gatekeeper, scoring, seed (the only service with a database)
├── red/          the fraud agent and its eight-scheme catalog
├── green/        the AP clerk
├── blue/         the controller: gate rules and the daily audit agent
├── agentkit/     shared Python: LedgerClient, EventEmitter, DroidAgent base, contract models
├── frontend/     Next.js: arena, backstage consoles, controls report
├── contracts/    schema.sql, ledger-api.yaml, events.md, agent-service.md, CHANGELOG.md
├── deploy/       Caddyfile and the bootstrap, env-render and prod scripts
├── docs/         the documents below, plus recordings/ (event streams of real prod runs)
├── devlog/       historical development notes (DEVLOG.md is the earlier frozen history)
└── AGENTS.md  GIT.md  Makefile  docker-compose*.yml  .env.example  LICENSE
```

## Docs

- [docs/STORY.md](docs/STORY.md): why this exists and what it found; the one source for every number we quote.
- [docs/EVIDENCE.md](docs/EVIDENCE.md): every claim with its proof, what not to claim, numbers, recordings, sources.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): services, the Ledger API's enforcement, each agent, evolution, scoring.
- [docs/FRONTEND.md](docs/FRONTEND.md): the site, its data flow and mock mode.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): running locally, environment variables, deploy and prod operations.
- [docs/CLOSEOUT.md](docs/CLOSEOUT.md): preserved submission, hosting retirement and remaining limits.
- [docs/PITCH.md](docs/PITCH.md): historical judging talk and demo instructions.
- [docs/SUBMISSION.md](docs/SUBMISSION.md): historical Devpost submission text.
- [docs/recordings/](docs/recordings/): operator event streams of real prod runs, indexed in docs/EVIDENCE.md.
- [contracts/](contracts/): the machine-readable API, schema and events; contracts win any disagreement with prose.
- [AGENTS.md](AGENTS.md) and [GIT.md](GIT.md): the working agreement and git protocol, for people and coding agents.

## Team

| Dev | Area |
|---|---|
| **Ad** | Backend and infrastructure: battlefield, agentkit, contracts, deploy, CI |
| **Al** | Red team: the attacker agent and its scheme catalog |
| **M** | Green, the AP clerk, and blue, the controller |
| **R** | Frontend design |

## License

MIT. See [LICENSE](LICENSE).
