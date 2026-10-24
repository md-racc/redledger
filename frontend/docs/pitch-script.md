# Pitch script: four voices, four laptops, about five minutes

The spoken pitch for the live demo. R opens and closes, then Green, Blue and Red each take a minute on their own laptop. Plain text is spoken. *[Italics in brackets]* are things to click. Laptop 1 is the arena, 2 is red, 3 is green, 4 is blue (the backstage consoles, see [backstage.md](backstage.md)). The show beats follow [show-mode.md](show-mode.md).

Before presenting, check the honest-status lines in R's close against what is actually live that day (the README and the Findings in `contracts/CHANGELOG.md` are the source).

## R

Would you let an AI pay your company's bills?

*[Beat.]*

Now, would you still say yes if someone was actively trying to trick it?

That's the part nobody tests. Before a car goes on the road, you crash it. Before an AI touches your money, you just hope. We didn't want to hope. So we built the crash-test lab. This is Red Ledger.

A small company, Coastal Supply Co. Three AI agents inside it, one shared ledger. Green pays the bills. Blue guards the money. Red tries to steal it.

Ninety seconds. Watch.

*[Press S on laptop 1. R talks only at these moments.]*

*[0:06, the tour]*

Ten guards, twelve clients, and red's catalog of ways to rob a company.

*[0:27, controller off]*

Round one: no guard. Watch the red number climb. That's what happens today when an agent has the checkbook and nobody's watching.

*[0:43, rewind, controller on]*

Rewind. Same company, same crime, guard on. The red number stays at zero.

*[About 0:55, the Your decision card appears. Click Block.]*

And when blue isn't sure, it does what a good employee does. It asks a person. If nobody answers, it blocks.

*[1:05, compare]*

Same crime. Different ending.

*[1:15, evolution]*

And between rounds, they learn. Red will explain.

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

I don't start with a mysterious AI score. I start with ten plain rules any auditor would recognize. Is this vendor under a week old? Did their bank account just change? Is the amount sitting just under the approval limit, the oldest trick in the book?

*[R clicks the Bank Change Watch guard on laptop 1.]*

Each rule is a guard in the arena. Watch my screen when R clicks one. There. It lights up here. Same system.

*[Point at the new block line.]*

And the bank swap we just launched? Blocked, by the bank-change rule. Read the reason: plain English, like an auditor's note. A sentence a human can argue with.

*[If it hasn't landed yet, point at any block already on screen.]*

Once a day I also audit the books and freeze suspicious vendors. And I'm graded both ways: dollars blocked, and the cost of blocking someone innocent. Block everything and I lose.

Red, you've been quiet.

## RED

*[Walk up to laptop 2.]*

I've been taking notes.

Red is the reason this means anything. If the attacker's weak, the defense proves nothing. So red is a real agent on Factory's Droid SDK. Every day it reads the company's books like a fraudster and picks a scheme that blends in: a ghost vendor, a bank swap, a duplicate invoice, a made-up employee.

But it's boxed in. It can submit invoices. It can't pay, approve, freeze, or read the audit log. It only sees what a real insider could see.

*[Point at the tape.]*

That bank swap blue just stopped? Mine. Decent plan. Rude.

Here's what's new. After every round, I get a debrief: which controls caught me. I rewrite my playbook. Blue sees what it missed and writes new rules.

*[R opens the Evolution card on laptop 1.]*

So round two is harder than round one. We're not testing an AI once. We're building two that sharpen each other.

R.

## R, to close

Would I hire an AI to run accounts payable? Not today. Not without proof. But now you can get proof: put an agent in a company, hand it a real attacker, and measure what the controls catch and what they cost.

To be straight about where we are: red is live on Factory's Droid SDK. Green and blue run their full logic, with their live sessions still clearing our safety checks. And that learning card was a recording of a loop that's real on the backend.

*[Say the version that's true on the day.]*

Now the fun part.

*[Turn laptop 1 toward the judge.]*

Pick an attack. Any one. Watch the other three screens.
