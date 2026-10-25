# Demo video: a three-minute storyboard

The Devpost entry needs a demo video of at most three minutes (`INTEGRATIONS.md` §4). This is a shot list you can record straight from
the site, with the words to say. Every line is a line from [pitch-script.md](pitch-script.md) or a number from the claims ledger, so
nothing here says more than the site shows. Read the **say it straight** notes before you record.

**Setup.** One laptop, a 1920×1080 window, a real GPU (not a remote desktop), the arena at `/` with `?q=3` for full quality. Press `S`
for the show where a row says *show*. Record the screen and your voice in one take per row, so a bad row is one retake. Keep the
backstage consoles (`/backstage/red`, `/green`, `/blue`) open in three more windows for row 6.

| # | Time | Screen | What to do | Say |
|---|---|---|---|---|
| 1 | 0:00–0:14 | the title and the flight over the Palace | start the page, let the intro run | "Would you let an AI pay your company's bills? Now, would you still say yes if someone was actively trying to trick it? That's the part nobody tests. So we built the crash-test lab. This is Red Ledger." |
| 2 | 0:14–0:30 | the scroll tour: guards, clients, fraudsters | press `S` (the show) | "A small company, Coastal Supply Co. Three AI agents, one shared ledger. Green pays the bills. Blue guards the money. Red tries to steal it. Ten guards, twelve clients, and eight fraud schemes." |
| 3 | 0:30–0:58 | the show's controller-off act, then controller-on | let the show run; do not click | "Round one: no guard. Watch the red number climb. Rewind. Same company, same crime, guard on. Now the blue number climbs instead. That's money stopped." Caption on screen says the show is a recording: leave it in. |
| 4 | 0:58–1:12 | the **Your decision** card | click **Block** | "And when blue isn't sure, it does what a good employee does. It asks a person. If nobody answers, it blocks." |
| 5 | 1:12–1:32 | **Compare**, then the **Real run** tab | open Compare, say the first line, click **Real run** | "Same crime, different ending. And here's a real run: red live, ten days, same seed. No controller, about ten thousand dollars lost. Controller on, about eighteen hundred. Not zero." |
| 6 | 1:32–1:55 | the three backstage consoles, side by side | click a guard in the arena (the same selection lights up on the other screens) | "Everything I click shows up on these three screens. Those are the real consoles, one per team: green's payments, blue's verdicts with their reasons, red's tape." |
| 7 | 1:55–2:15 | the **Evolution** card | open it | "We let red run five generations against our controls, live, with its first five schemes. It found the one scheme nothing flagged, invoices split just under the approval limit, and leaned on it harder every round: about nineteen thousand dollars in round one, about ninety-seven thousand in round five. That's what the lab is for. It found a hole before anyone hired an agent." |
| 8 | 2:15–2:42 | **Launch attack**, then **Speak a scheme** | click **Launch attack**, press **Speak a scheme**, say a sentence in another language, pause (it stops by itself), click **Launch it** | "Anyone can try to break it. Say a scheme in your own words, in any language. ElevenLabs turns it into text, red reads it, and the closest of its eight schemes runs. Watch the guards." Then cut to the backstage red and blue consoles for two seconds. |
| 9 | 2:42–3:00 | the arena, the HUD's **Source** and **Agents** badges in frame | stop on the arena | "To be straight about where we are: red is a live agent. Green and blue run their full logic keyless. The show is a recording, and the learning card is a recorded live run. Would I hire an AI to run accounts payable? Not today. Not without proof. Now you can get proof." |

## Say it straight (do not cut these)

- The 90-second show is **a recording** (mock agents). The caption says so; the row 3 voice-over says so.
- Red is **live** (Factory's Droid SDK). Green and blue run their **full logic keyless**; their live sessions are still clearing our safety checks.
- Blue **asks a person** for a bank swap; the human, or the timeout, does the blocking. Do not say blue "blocks" it.
- "Ten guards" is the arena roster, not an exact count of blue's rules. Blue switches on pre-written learned controls; it does not write rules.
- "Eight schemes built" follows `red/schemes` on `main`. The five-generation result is on the first five. If the claims ledger (`docs/devpost/hyphenate.md` §8) still says five, ask Ad before you say eight in a recording.
- Voice needs the speech key on the server. If the console says voice is not set up, use a **Try** chip: the beat is the same.

## After recording

Cut to 3:00 or under, add the repo URL on the last frame, and export 1080p. Do not put keys, tokens or the admin page (`/admin`) on
screen.
