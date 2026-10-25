# Pitch: video and judging talk

Everything here is cut from [STORY.md](STORY.md). Numbers come from [EVIDENCE.md](EVIDENCE.md). If a line here disagrees with STORY.md, STORY.md wins: change it there first.

**Rules for every speaker:**
- Never call a block a catch unless the card shows a rule. A fail-safe block, when blue is unreachable, is labelled as one. Read the reason line before you narrate it.
- Say "synthetic company, real schemes" whenever money comes up.
- The two controller-off/on numbers are **$10,285** and **$0**. Don't round them differently and don't quote $1,824; that figure is from before rescoring.

---

## 1. The 90-second video (Dev R)

About 215 words of voiceover, at about 145 words a minute.

**Screens:**
- **The arena** for 0:20.
- **Red's and blue's consoles in replay** (`/backstage/red?replay=1`, `/backstage/blue?replay=1`) for 0:33. They replay `recordings/demo-enforce-live.jsonl`, controller on, where red's bank-account swap is held.
- **The Compare card's "Real run" tab** for 0:50.
- **The Evolution card** for 1:03: first `?lineage=ln_f52a3df83c8d`, then `?lineage=ln_431bf702e8a0`.

Every shot is a recording or a finished run, so every take comes out the same.

| Time | On screen | Voiceover (word for word) |
|---|---|---|
| 0:00–0:12 | Black. Text cards fade in: "Arup · Hong Kong · 2024", then "HK$200,000,000". | "In 2024, a finance worker at Arup joined a video call with his CFO. Every face on that call was a deepfake. He sent twenty-five million dollars." |
| 0:12–0:20 | Text card: "Fraud gets past whoever approves the payment." Then: "That job is going to AI agents." | "Fraud like this works by getting past whoever approves the payment. And that job is going to AI agents." |
| 0:20–0:33 | The arena: the company and its three agents, each labelled as it's named. | "Red Ledger is the crash test. A live AI fraud agent attacks a company's books. An AI clerk pays the bills. And a controller rules on every payment before it moves." |
| 0:33–0:50 | Red's console asks to change a vendor's bank account. Cut to blue's console: the **ESCALATE** card. Zoom on "Needs independent verification: destination change overlaps open invoices." | "Red asks to change a vendor's bank account. That's the move that took a hundred and twenty million dollars from Google and Facebook. The clerk would approve it. But the ledger asks the controller first, and the change is held until someone verifies it." |
| 0:50–1:03 | Compare card, "Real run" tab: controller off vs on, same seed. | "Same company, same ten days. Controller off: that one swap cost ten thousand dollars. Controller on: zero." |
| 1:03–1:20 | Evolution card for ln_f52a3df83c8d climbing from $19k to $98k, then the card for ln_431bf702e8a0 at $0. | "Then we let red learn. Over five generations it found that invoices split just under the approval limit got paid, and it climbed to ninety-eight thousand dollars. None of our controls caught it. We closed the gap in the ledger, and the next live run stole nothing." |
| 1:20–1:30 | Title card: "Red Ledger", then "app.redledger.us · github.com/…". | "Before your agent gets the checkbook, crash-test it. Red Ledger." |

**Atlassian allows a video up to 3 minutes.** If we want a longer cut for Atlassian, add 0:30 after 1:20: the controls report (`/report/<ep>`) and the audit log ("every action, with its inputs and its reason"). Otherwise one 90-second video goes to every track.

---

## 2. The 5-minute judging talk

**The one moment it builds to:** the judge attacks the company, then decides whether the money moves.

**Before each judge arrives:**
- Four laptops, all signed in as admin at `/admin`:
  1. the arena (R)
  2. red's console (Al)
  3. blue's console (M)
  4. the escalation panel and the latest controls report (Ad)
- The continuous run is going in enforce mode.
- A fifth tab on laptop 3 is paused on a recorded ESCALATE or BLOCK card. That's the fallback.
- The track card is on the table face up (see §3).

**Timing to expect** (measured on prod): red attacks at the start of each simulated day, and a day takes 20–30 seconds. An escalation waits up to 90 seconds for a person, then blocks. A judge's request reaches red on its next turn, so plan on 30–60 seconds before green acts on it.

### Al — 0:00 to 0:40 (laptop 2, the hook)

> In January 2024, a finance worker at Arup in Hong Kong got on a video call with his CFO and a few colleagues. Every one of them was a deepfake. He sent twenty-five million dollars, in fifteen transfers.
>
> Fraud like that has always worked the same way: get past whoever approves the payment. Companies are now handing that job to AI agents.
>
> So this weekend, I built the thief. Red is an AI agent that reads a company's books like a junior employee would, and steals from it, using eight schemes taken from real cases.
>
> Want to try? Tell red what to steal. Anything. Something like "change our supplier's bank account to mine."
>
> *(The judge types it into red's console on laptop 2. Al submits it.)*
>
> That goes to red as a request. It picks the scheme that fits and goes after it.

### R — 0:40 to 1:30 (laptop 1, the company)

> While red works on that, here's what it's attacking. A synthetic company with real-looking books: sixty vendors, forty employees, three months of history. Three AI agents work inside it, and none of them can see the others.
>
> Red is the thief. Green is the accounts-payable clerk: it pays the bills. Blue is the controller. Before any money moves, blue says allow, block, or ask a human.
>
> This is running live, right now.
>
> And this isn't hypothetical. *(Press L.)* Last week Axios reported that big US banks are finding AI agents they never vetted inside customer accounts, and that they can't yet tell a good one from a rogue one. We test the version that's already inside the books.

### M — 1:30 to 2:45 (laptop 3, the defense, and the numbers)

> Here's your attack. Red has made its move, and green, the clerk, is about to act on it.
>
> *(The card appears.)*
>
> Before anything moves, the ledger asks blue. *(If it's an ESCALATE card:)* Blue isn't sure, so it's asking a human. That's you. Approve, or block? *(The judge decides on laptop 4. If BLOCK:)* Blue says no. Here's the rule that fired, the reason in plain English, and the audit row behind it.
>
> The important part: this happens in the ledger, not in the clerk's prompt. Even if green is completely fooled, the money doesn't move.
>
> Does it work? Same company, same ten days. With the controller off, red swapped one vendor's bank account and took ten thousand two hundred eighty-five dollars. With it on, that change was held for verification, and red got zero.
>
> Then we let red learn across generations. It found that invoices split just under the approval limit got paid, and it climbed from nineteen thousand dollars a run to ninety-eight thousand. None of our controls caught it. That's what a crash test is for. We added the rule in the ledger, and in the next run, with red and blue both live for three generations, red stole nothing.
>
> One honest limit: blue caught three of red's twelve attempts in that run. The other nine never got paid out. And blue doesn't learn new rules yet. That's next.

**If the judge's attack hasn't produced a card by 1:50**, M says: "Red's still working on yours. Here's one from earlier." He switches to the fallback tab, reads that card, then checks the live tab again at 2:30.

### Ad — 2:45 to 3:45 (laptop 4, it's real, plus the track line)

> This isn't a mockup. It's five services and a database, hosted on Vultr behind Cloudflare. Only the ledger service can touch the database. Every agent has its own key, can't see the scoreboard, and never sees which rows are fraud. Every deploy goes through eight CI checks and a manual production approval, and there are about fifteen hundred automated tests. Red and blue run on Factory's Droid SDK, and a red turn costs about a cent.
>
> *(Read the one line for this judge's track from §3.)*
>
> Every big accounts-payable fraud got past a person. The next ones will try to get past an agent. Red Ledger is how you find out first.

### Questions — 3:45 to 5:00 (Ad routes them)

| If they ask | Who answers | The answer |
|---|---|---|
| Is the money real? | Al | No. The company is synthetic, and every scheme is one that has stolen real money. |
| How does red know what to do? | Al | It reads the books through the same API the clerk uses, and picks from eight schemes. Your request steers which one. |
| What stops the clerk from just paying? | M | The ledger. The clerk has no database access. Every payment route checks blue's verdict first, and the ledger enforces it. |
| Why not put the rules in the prompt? | M | A prompt can be talked around. A ledger rule can't. |
| Is blue an LLM? | M | Two parts. The gate is deterministic rules, so it's fast and auditable. The daily audit is a live Droid agent that raises flags, and the gate enforces those flags. |
| What about false positives? | M | They're scored: $50 plus 2% of the amount for every legitimate payment blocked. Blocking everything loses. |
| What isn't done? | Ad | On prod the clerk runs our logic without a model; its live Droid turn is built but off until it passes acceptance. Blue doesn't learn new rules yet. |
| What would a company do with this? | Ad | Point its AP agent at this ledger, let red attack it for a few simulated weeks, and read the controls report: what fired, what got through, what it cost. |
| How much does it cost? | Ad | Cents per simulated day. A red turn is about 2,800 Factory credits. |
| Why does it look like this? | R | *(R's own words on the design.)* |
| Which banks said that? | R | *(Press L.)* Each one is on the card with its source. Wells Fargo has said nothing we could find, and Morgan Stanley says it hasn't seen one. |

---

## 3. Track card (one line each, Ad reads the one for the judge's badge)

- **Hyphenate:** The clerk does accounts payable end to end, and people only see the calls that need judgment: an escalation, with a reason and 90 seconds to answer. What makes that safe to hand over is measured here, in dollars, in both directions.
- **Factory:** Green and blue run Droid with autonomy off, so every tool call raises a permission request. We made that request the control point: the handler asks the ledger before it says yes.
- **Microsoft:** It's built to run like a real product: hosted, CI-gated, isolated per agent, public, and running live adversarial episodes in production since Saturday.
- **CRS:** Ghost employees are real payroll fraud. Blue checks identities against CRS. In a live production run, an identity mismatch got that employee's next expense blocked at the gate.
- **Armadin:** The attacker is the engine. It's an agent with an insider's view that picks its schemes, adapts between generations, and found a gap our defenders missed.
- **Atlassian (Security for agents):** Every action an agent takes is checked before it happens, in the system of record, and logged with its inputs and reasoning. The guardrail sits outside the agent, where no prompt can reach it.
- **Most Technically Advanced:** The hard part was the protocol. The agent learns the verdict before it acts, with no second source of truth. Agents learn across generations without ever seeing which rows are fraud during play.
