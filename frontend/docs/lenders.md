# The lenders: what they have said, and the proof

Why a lender would want a crash-test lab like this one: in October 2026 the largest US banks started saying, in public, that outside AI agents are getting into customer accounts, and that they cannot yet tell a good one from a rogue one. This page is every line we say about them, with its source. The same table is on the **Lenders** card in the arena (press `L` anywhere, or the **Lenders** button once you are in the arena; `Esc` closes it; `lib/arena/lenders.ts`, checked by `lib/arena/lenders.test.ts`) and in [pitch-script.md](pitch-script.md).

Researched **2026-10-25** from reporting dated 2026-10-15 to 2026-10-23. Everything below is a paraphrase of someone else's reporting or statement. **These banks are not partners, customers or sponsors of Red Ledger**, and none of this is their statement about us. Re-check before you say it on stage: the story is days old and moving.

## The report everything follows

**Axios, "Scoop: Unvetted AI agents are accessing U.S. bank accounts"**, Madison Mills, 2026-10-22 ([read as syndicated by Yahoo Finance](https://finance.yahoo.com/technology/ai/articles/scoop-unvetted-ai-agents-accessing-090006442.html); the Axios original is paywalled).

- Large US banks are finding third-party AI agents they never vetted inside customer accounts, mostly logging in with the customer's own password. Some agents did things the customer had not asked for (an agent phoned a bank with a complaint, for one). Most banks allow, or are moving to, read-only access.
- A bank executive is quoted saying banks struggle to tell an authorised agent from a rogue one.
- **The sourcing is anonymous** ("people familiar with the matter"). On the record in it: a Chase spokesperson (do not share passwords) and a Morgan Stanley spokesperson (see below).
- Mills told CBS the agents were not hacking accounts or draining funds, and that it is industry-wide, dozens of institutions ([CBS News](https://www.cbsnews.com/news/ai-agents-customer-bank-accounts-security/), Megan Cerullo, 2026-10-23).

## The five

"On the record" means a named executive or a bank spokesperson said it, as reported. Where the outlet is second-hand, the table says so.

| Lender | Where it stands | On the record | Sources |
|---|---|---|---|
| **JPMorgan Chase** | Won't let outside agents in | CEO Jamie Dimon, Q3 earnings call, 2026-10-13: the bank will not let outside AI agents inside, and he warned of "rogue agents". A spokesperson: when the bank detects a third-party agent using a customer's banking credentials, it does not allow it. Read-only data through open-banking connectors continues; no timeline for agents to act. | [Fortune](https://fortune.com/2026/10/15/jamie-dimon-ai-agents-meta-muse-jpmorgan/), Joshua Hong, 2026-10-15; [CBS News](https://www.cbsnews.com/news/ai-agents-customer-bank-accounts-security/), 2026-10-23 |
| **Bank of America** | A human approves money out | CEO Brian Moynihan, to CNBC: a person should approve any money leaving an account; the bank is working out who is liable when an AI authorises a payment. The Financial Times reported, from an unnamed source, that it limits agents' access to consumer deposits. The bank did not answer CBS. | [Retail Banker International](https://www.retailbankerinternational.com/?p=108841), Vidhya Edwards Munnangi, 2026-10-19 (second-hand from the FT and CNBC); [PYMNTS](https://www.pymnts.com/?p=4326961), 2026-10-19 (second-hand) |
| **Citi** | No outside agents; read-only via approved providers | A spokesperson to Retail Banker International: Citi does not let third-party AI agents or assistants log in to a customer's account or transact on its digital banking platforms; customers can still give read-only access through approved open-banking providers. | [Retail Banker International](https://www.retailbankerinternational.com/?p=108841), 2026-10-19 |
| **Wells Fargo** | No statement found | **Nothing on outside agents in customer accounts that we could find.** CEO Charlie Scharf, Q3 call: a disciplined approach to risk, and the bank will weigh whether third-party models and agents add value for clients. Axios lists Wells Fargo among banks "racing to contain" agent risk, with no detail; the bank did not answer CBS. | [Banking Dive](https://www.bankingdive.com/news/ai-citi-fraser-wells-fargo-scharf-goldman-sachs-solomon-morgan-stanley-pick-bofa-moynihan-dimon/833087/), Makenzie Holland, 2026-10-15; Axios (above) |
| **Morgan Stanley** | Says it has seen none | A spokesperson to CBS: the firm has not observed unauthorized AI agent activity on its platforms. Axios, from anonymous sources, says it has begun blocking third-party agents. The two accounts are not reconciled. | [CBS News](https://www.cbsnews.com/news/ai-agents-customer-bank-accounts-security/), 2026-10-23; Axios (above) |

Also on the record in the same reporting, not among the five: **Charles Schwab**, CEO Rick Wurster, to Bloomberg on 2026-10-16, blocks unauthorized agents that try to log in for clients and will not let outside agents move money ([PYMNTS](https://www.pymnts.com/?p=4326961), second-hand); **PNC**, CEO William Demchak, Q3 call 2026-10-15, called agents transacting inside customer accounts unsafe and said it would take liability law and secure authentication ([PYMNTS](https://www.pymnts.com/news/banking/2026/banks-crack-down-on-unauthorized-ai-agents-operating-inside-customer-accounts/), 2026-10-22, second-hand).

## What we say, and what we do not

**Say** (these are in [pitch-script.md](pitch-script.md)):

- "Axios reported that big banks are finding AI agents they never vetted inside customer accounts." (It is Axios's report, on anonymous sources.)
- JPMorgan Chase won't let outside agents in. Bank of America wants a human approving any money out. Citi blocks them. Morgan Stanley says it hasn't seen one. Wells Fargo has said nothing we could find.
- Nobody can yet tell a good agent from a rogue one once it is inside. (The reported difficulty.)
- Red Ledger tests that case: an agent already inside the books, and a gate that must say allow, block, or ask a human. A human approving money out is the rule our gate escalates to, and no answer in 90 seconds is a block.

**Do not say:**

- That any named bank *found* agents in its accounts, *lost* money, or *was attacked*. Only Axios's anonymous sources say banks are finding agents, and none of the five has put a number or an incident on the record.
- That Morgan Stanley is blocking agents as a fact (anonymous sources), or that it has seen some (it says it has not).
- That Wells Fargo has a position on this.
- That any of them uses, wants, endorses or has heard of Red Ledger. No logos, no quotation marks around anything longer than a few words.
- Anything about their customers' accounts being "hacked": the reporter says the agents were using the customer's own credentials, not breaking in.

## Where the old synthetic company went

The demo's company is still seeded by the backend (`battlefield/seed/`), which this folder does not own. In `frontend/` it is now "the company" or "the synthetic company" everywhere (arena copy, the report, the pitch, the storyboard, the docs, the stand-in battlefield). A test (`lib/arena/lenders.test.ts`) keeps the old name out of `frontend/`. If the lenders become the demo's setting rather than its context, that is a seed and prompt change for Ad, Al and M.
