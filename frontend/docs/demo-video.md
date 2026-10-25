# Demo video: a three-minute storyboard

The Devpost entry needs a demo video of at most three minutes (`INTEGRATIONS.md` §4). This is a shot list you can record straight from the site. The words are the lines of [pitch-script.md](pitch-script.md), cut to three minutes, and each row names the **sponsor feature** the judges for that prize are listening for ([sponsors.md](sponsors.md) has the proof). Read **Say it straight** before you record.

**Setup.** One laptop, a 1920×1080 window, a real GPU (not a remote desktop), the arena at `/` with `?q=3`. Press `S` where a row says *show*. Record the screen and your voice together, one take per row, so a bad row is one retake. Keep the red and blue backstage consoles open in two more windows for row 5. Put the sponsor names on screen as small lower-thirds the moment you say them.

| # | Time | Screen | What to do | Say | Sponsor on screen |
|---|---|---|---|---|---|
| 1 | 0:00–0:24 | the title and the flight over the Palace, then the **Lenders** card for the bank sentences | start the page, let the intro run, press `L` | "It's Friday, 4:55 p.m. An email lands: 'We've changed banks. Please update our account.' A tired clerk might pay it. An AI would pay it faster. And it's already here: this month Axios reported that big banks are finding AI agents they never vetted inside customer accounts. JPMorgan Chase won't let outside agents in; Bank of America wants a human approving any money out; Morgan Stanley says it hasn't seen one. Nobody is testing what an agent does once it's inside. So we built the crash-test lab. This is Red Ledger." | |
| 2 | 0:24–0:38 | the scroll tour: guards, clients, fraudsters | press `L` again to close the card, press `S` | "Meet the company we built: sixty vendors, ninety days of history, one ledger, three AI agents. Green pays the bills. Blue guards the money. Red wants it. All three are built on Factory's Droid SDK." | **Factory** Droid SDK |
| 3 | 0:38–1:00 | the show's controller-off act, then controller-on, then **Your decision** | let the show run; click **Block** | "No guard: watch the red number climb. Same crime, guard on: the blue number climbs. That's money stopped. When blue isn't sure, it asks a person. That's Hyphenate's test, knowing when to ask. Nobody answers? Blocked." The caption saying it is a recording stays in. | **Hyphenate** |
| 4 | 1:00–1:20 | **Compare**, then the **Real run** tab | open Compare, click **Real run** | "Here's a real run. Red live, ten days, same seed: about ten thousand dollars gone with no controller, about eighteen hundred with one. Not zero, and we'll say so." | |
| 5 | 1:20–1:45 | the red and blue backstage consoles, side by side | click a guard in the arena; point at red's thinking lines, then blue's verdict log | "Red's reasoning streams in as it thinks: live on Factory's Droid SDK. Every verdict blue gives is a row in an append-only log, built as Tiger Data TimescaleDB hypertables and tested on the real thing in CI." | **Factory**, **Tiger Data** |
| 6 | 1:45–2:10 | the **Evolution** card | open it | "But red can't cheat. That's what makes this a range for Armadin: it can't see which rows are fraud, grade itself, or pose as blue. Then we let it learn: five generations, live. It found the hole nothing flagged, invoices split just under the limit: about nineteen thousand dollars in round one, about ninety-seven thousand in round five. That's what a lab is for." | **Armadin** |
| 7 | 2:10–2:35 | **Launch attack**, then **Speak a scheme** | press **Speak a scheme**, say a sentence in another language, pause (it stops by itself), click **Launch it**, cut to the red and blue consoles for two seconds | "Your turn: say an attack in your own words, in any language. ElevenLabs' speech-to-text hears it and names the language. Red reads your sentence and runs the closest of its eight schemes." | **ElevenLabs** |
| 8 | 2:35–3:00 | the arena with the **Source** and **Agents** badges in frame, then the deck's **Built with our sponsors** slide | stop on the arena, then cut to the slide | "To be straight about where we are: red and blue's audit are live. Green is keyless on the same harness. The show is a recording. Under the glass: one Vultr VM behind Cloudflare, an approval-gated deploy. Would I hire an AI to pay that email? Not today. Not without proof. Now you can get proof." | **Vultr**, and all six names |

## Say it straight (do not cut these)

- The 90-second show is **a recording** (mock agents). The caption says so; the row 3 voice-over says so.
- Red is **live** (Factory's Droid SDK), and so is blue's daily audit. Green runs its full logic **keyless** on the same harness. Blue's gate is deterministic rules, not a model.
- Blue **asks a person** for a bank swap; the human, or the timeout, does the blocking. Do not say blue "blocks" it.
- Tiger Data: TimescaleDB is proven **in CI**; **production runs plain Postgres 16**. Never say "in production".
- ElevenLabs: the ledger says it was never tested against the real service. Record one real transcription first. If it fails, use a **Try** chip and cut the ElevenLabs sentence.
- "Eight schemes built" follows `red/schemes` on `main` and the claims ledger (`docs/devpost/hyphenate.md` §4, #181). The five-generation result is on the first five.
- Lenders: say only what the **Lenders** card shows, with its source on screen ([lenders.md](lenders.md)). JPMorgan Chase and Citi say they block outside agents, Bank of America wants a human approving money out, Morgan Stanley says it has seen none, we found no statement from Wells Fargo. Never say a bank "found agents in its accounts" unless that bank said so (Axios's per-bank claims are anonymous), and never imply a bank uses or endorses Red Ledger.
- CRS is not in this video: it needs a separate live table demo ([sponsors.md](sponsors.md)).

## After recording

Cut to 3:00 or under, add the repo URL on the last frame, and export 1080p. Do not put keys, tokens or the admin page (`/admin`) on screen.
