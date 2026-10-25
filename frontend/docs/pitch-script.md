# Pitch script: four voices, four laptops, about five minutes

The spoken pitch for the live demo. R opens and closes, then Green, Blue and Red each take a minute on their own laptop. Plain text is spoken. *[Italics in brackets]* are things to click. Laptop 1 is the arena, 2 is red, 3 is green, 4 is blue (the backstage consoles, see [backstage.md](backstage.md)). The show beats follow [show-mode.md](show-mode.md).

Every claim here follows the claims ledger in [`docs/devpost/hyphenate.md`](../../docs/devpost/hyphenate.md) §8 and the numbers sheet in §10. In particular: the real blue **escalates** a bank swap (a human or the timeout does the blocking), it switches on pre-written learned controls rather than writing rules, the 90-second show is a recording with the mock agents, and the evolution card shows the newest finished backend lineage (the live-red one on prod). **Eight schemes:** `red/schemes` on `main` has all eight (#166), so this script says all eight are built. The claims ledger (`hyphenate.md` §8) and the Devpost drafts still say five exist and three are planned, and the live five-generation run was on the first five. Ask Ad that the ledger is brought up to date before saying "eight built" on stage. The arena's captions (`lib/arena/timeline.ts`, `lib/arena/roster.ts`) say the same as this script, so if the ledger stays at five, change the captions and these lines back together. Before presenting, check the status lines in R's close against what is live that day. The spoken-scheme moment at the end needs the speech key on the server (see [voice.md](voice.md)): press **Speak a scheme** once before you go on, and if the console says voice is not set up, use the Try chips or type, which the script covers.

## R

Let me start with a question.

Would you let an AI pay your company's bills?

*[Beat.]*

Now, would you still say yes if someone was actively trying to trick it?

That's the part nobody tests. Before a car goes on the road, you crash it. Before an AI touches your money, you just hope. We didn't want to hope. So we built the crash-test lab. This is Red Ledger.

A small company, Coastal Supply Co. Three AI agents inside it, one shared ledger. Green pays the bills. Blue guards the money. Red tries to steal it.

Ninety seconds. This part is a recording with our test agents, so it plays the same every time. Watch.

*[Press S on laptop 1. R talks only at these moments.]*

*[0:06, the tour]*

Ten guards, twelve clients, and red's fraudsters. Eight on the wall, all eight built.

*[0:27, controller off]*

Round one: no guard. Watch the red number climb. That's what happens today when an agent has the checkbook and nobody's watching.

*[0:43, rewind, controller on]*

Rewind. Same company, same crime, guard on. Now the blue number climbs instead. That's money stopped.

*[About 0:55, the Your decision card appears. Click Block.]*

And when blue isn't sure, it does what a good employee does. It asks a person. If nobody answers, it blocks.

*[1:05, compare]*

Same crime. Different ending. In this recording, anyway. I'll tell you what the live numbers look like.

*[1:15, evolution]*

Then we run it again and again, live, and watch what red learns. Red will tell you.

*[1:28, click any client on laptop 1]*

That's the site. Everything I click here shows up on these three screens. That's the real backend, one per team.

Green, you're up.

## GREEN

*[Walk up to laptop 3.]*

Hi. I'm the one you'd trust with your checkbook. That's the problem.

Green is the finance clerk. It matches invoices to purchase orders, pays bills, reimburses expenses. Those are the company's real books, live.

*[Point at AP open, overdue, cash.]*

And it's gullible on purpose. It never checks how old a vendor is, or whether their bank account just changed. If the paperwork looks right, it pays, like any busy clerk on a Friday. That's exactly what a fraudster counts on.

So we didn't make green paranoid. We made it ask first. Before green moves a dollar, the ledger asks blue: allow, block, or get a human. Block means the payment dies before the money moves.

*[Point at the list of gated payments.]*

Every line here is a payment green tried to make, and blue's answer.

Let's see how gullible I am.

*[R opens Launch attack on laptop 1 and clicks Bank Account Swap.]*

Blue?

## BLUE

*[Walk up to laptop 4.]*

"Gullible on purpose." Thanks, green. That's why I exist.

I don't start with a mysterious AI score. I start with plain rules any auditor would recognize. Some block outright. Some ask a human. Some just leave a note on the payment. Is this vendor under a week old? Did their bank account just change? Is the amount sitting just under the approval limit?

*[R clicks the Bank Swap Trap guard on laptop 1.]*

Each rule is a guard in the arena. Watch my screen when R clicks one. There. It lights up here. Same system.

*[Point at the new line.]*

And the bank swap we just launched? I didn't block it. I flagged the bank change and asked a human.

*[R clicks Block on the Your decision card on laptop 1.]*

There. A person decides. Read my reason: plain English, like an auditor's note. And if nobody answers in ninety seconds, it blocks anyway.

*[If the line says BLOCK instead, say: blocked.]*

Once a day I also audit the books and freeze suspicious vendors. And I'm graded both ways: dollars blocked, and the cost of blocking someone innocent. Block everything and I lose.

Red, you've been quiet.

## RED

*[Walk up to laptop 2.]*

I've been taking notes.

Red is the reason this means anything. If the attacker's weak, the defense proves nothing. So red is a real agent, live on Factory's Droid SDK. Every day it reads the company's books like a fraudster and picks a scheme that blends in: a ghost vendor, a bank swap, a duplicate invoice, an invoice split into pieces, a made-up employee, padded expenses, an invoice over its purchase order, a price that creeps up every month.

But it's boxed in. It can submit invoices. It can't pay, approve, freeze, or read the audit log. It only sees what a real insider could see.

*[Point at the tape.]*

That bank swap blue just sent to a human? Mine. Decent plan.

But here's the part that surprised us. We let red run five generations against our controls, live, with its first five schemes. After every round it gets a debrief: which controls caught it. It found the one scheme nothing flagged, invoices split just under the approval limit, and leaned on it harder every round. Round one, it took about nineteen thousand dollars. Round five, about ninety-seven thousand.

Blue switched on its learned controls. None of them fired on a split.

*[R opens the Evolution card on laptop 1.]*

That's what the lab is for. It found a hole before anyone hired an agent.

R.

## R, to close

Would I hire an AI to run accounts payable? Not today. Not without proof. But now you can get proof: put an agent in a company, hand it a real attacker, and measure what the controls catch and what they cost.

Here's what live looks like. Real agents, ten days, same seed. No controller: about ten thousand dollars lost. Controller on: about eighteen hundred. Not zero.

And to be straight about where we are: red is a live agent. Green and blue run their full logic keyless, and their live sessions are still clearing our safety checks. The show was a recording, and that learning card is a recorded live run.

*[Say the version that's true on the day.]*

Now the fun part.

*[Turn laptop 1 toward the judge. Open Launch attack.]*

Pick an attack. Or make one up. Press Speak a scheme and say it in your own words, in whatever language you like. Then just pause. It stops listening when you do.

*[They speak. The words appear in the box, with the language it heard. Click Launch it. No microphone, or voice is off that day: click a Try chip, or have them type it.]*

ElevenLabs turned your voice into text, and there's your sentence on the red screen. Red reads it as you said it, and uses it to set the amount and details. The scheme it runs is the closest of its eight. Now watch the other three screens.

*[If it lands on Bank Account Swap, blue asks a human: say so and click Block. If it lands on Ghost Vendor, it gets through with a note. Say: that's the documented gap, a small new vendor gets a note, not a block. A plain button pick behaves the same way.]*
