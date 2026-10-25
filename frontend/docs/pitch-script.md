# Pitch: four voices, two pages

About five minutes, spoken. Plain text is said aloud; *[italics in brackets]* are clicks; **bold** is a sponsor's name: say it clearly. Laptop 1 is the arena, 2 red, 3 green, 4 blue ([backstage.md](backstage.md)). Claims follow the ledger ([`hyphenate.md`](../../docs/devpost/hyphenate.md) §8); check R's status lines against what is live that day. Proof for every sponsor line: [sponsors.md](sponsors.md).

## R: open

It's Friday, 4:55 p.m. An email lands: "We've changed banks. Please update our account." A tired clerk might pay it. An AI would pay it faster. *[Beat.]*

Everyone is building the agent that pays your bills. Nobody is testing it against someone trying to steal. Before a car goes on the road, you crash it. Before an AI touches your money, you just hope. We didn't want to hope. So we built the crash-test lab. This is Red Ledger.

Meet Coastal Supply Co.: sixty vendors, ninety days of history, one ledger, three AI agents. Green pays the bills. Blue guards the money. Red wants it. All three are built on **Factory's Droid SDK**, and you'll see which are live.

*[Press S: ninety seconds, a recording with our test agents.]*

No guard: watch the red number climb. *[Controller on.]* Same crime, guard on: the blue number climbs. That's money stopped. *[Your decision card: click Block.]* When blue isn't sure, it does what a good employee does: it asks a person. That's **Hyphenate's** test, knowing when to ask. Nobody answers? Blocked.

Green, you're up.

## GREEN: laptop 3

I'm the one you'd trust with your checkbook. That's the problem. I match invoices to purchase orders, pay bills, reimburse expenses, and I'm gullible on purpose: if the paperwork looks right, I pay, like any busy clerk on a Friday.

So nobody made me paranoid. They made me ask first. Before I move a dollar, the ledger asks blue: allow, block, or get a human. Block means the payment dies before the money moves. *[Point at the gated payments.]* Every line is a payment I tried, and blue's answer. I run keyless, on the same harness as the live agents.

Let's see how gullible I am. *[R: Launch attack, Bank Account Swap.]* Blue?

## BLUE: laptop 4

"Gullible on purpose." Thanks, green. I don't use a mystery score. I use rules any auditor would recognize. Is the vendor a week old? Did their bank account just change? Is the amount just under the limit? *[R clicks a guard: it lights up here.]* Same system.

That bank swap? I didn't block it. I flagged it and asked a human. *[R clicks Block.]* Every verdict I give is a row in an append-only log, built as **Tiger Data** TimescaleDB hypertables and tested on the real thing in CI, so we can rewind any day and watch it again. And once a day I audit the books live on Droid, at autonomy "off," where every tool call I make is a permission request.

I'm graded both ways: dollars blocked, and the cost of blocking someone innocent. Block everything and I lose. Red, you've been quiet.

---

## RED: laptop 2

I've been taking notes. If the attacker's weak, the defense proves nothing. So I'm a real agent, live on **Factory's Droid SDK**, at autonomy "high": nobody asks me permission. *[Point at the thinking lines.]* Watch my reasoning stream in. Every day I read the books like a fraudster and pick one of eight schemes: ghost vendors, bank swaps, duplicate invoices, splits under the limit, ghost employees, padded expenses, inflated purchase orders, creeping prices.

But I can't cheat. That's what makes this a range for **Armadin**, not a demo. I can't see which rows are fraud, grade myself, or pose as blue. I can't pay, approve, freeze, or read the audit log. Reviewers found fourteen ways the sandbox could leak or be gamed; we closed them before merging. That bank swap blue just sent to a human? Mine. *[Point at the tape.]*

Then we let me learn: five generations, live, with my first five schemes. I found the hole nothing flagged, invoices split just under the limit, and leaned on it every round: about nineteen thousand dollars in round one, about ninety-seven thousand in round five. *[R opens Evolution.]* None of blue's rules fired. That's what a lab is for. R.

## R: close

Back to that Friday email. Would I hire an AI to pay it? Not today. Not without proof. Here's a real run. *[Compare, then Real run.]* Red live, ten days, same seed: about ten thousand dollars gone with no controller, about eighteen hundred with one. Not zero, and we'll say so.

Where we are: red and blue's audit are live. Green is keyless on the same harness. The show was a recording, and the learning card is a recorded live run. *[Say the version that's true on the day.]*

Under the glass: one **Vultr** VM behind Cloudflare, an approval-gated deploy, and compare-and-set commits, so parallel calls can't pay an invoice twice. The browser never holds a key.

Your turn. *[Turn laptop 1 to the judge.]* Pick an attack, or say one in your own words, in any language. *[Only if the pre-check worked: **ElevenLabs'** speech-to-text hears it and names the language.]* Red reads your sentence and runs the closest of its eight schemes. Go on: try to steal from Coastal Supply. Watch the other three screens.

## Sponsors: the feature we showcase

| Sponsor, prize | Feature we use | Where you see it | Straight status |
|---|---|---|---|
| **Factory**, Droid SDK | autonomy levels, streamed thinking, tool-call IDs as idempotency keys | red's reasoning; blue's audit | red, blue's audit live; green keyless |
| **Hyphenate**, finance | gate, audit log, human escalation, evolution | Your decision; Evolution | in the demo |
| **Tiger Data**, MLH | TimescaleDB hypertables, continuous aggregate | blue's verdict log | CI on TimescaleDB; production Postgres 16 |
| **Vultr**, MLH | the VM | the whole site | live |
| **Microsoft**, **Most Technically Advanced** | approval-gated deploy, compare-and-set, Cloudflare Access | the close | live |
| **Armadin**, Best Security Hack | boxed-in AI attacker, hidden ground truth | red's minute | live |
| **ElevenLabs** | speech-to-text, language detection | the judge's turn | check one real recording first |
| **CRS** | identity sandbox | a separate table demo | proven locally |
