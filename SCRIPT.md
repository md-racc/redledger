# Script: the 90-second video

For Dev R. This is the Devpost video, line by line. It's cut from [STORY.md](STORY.md), and every number is backed in [EVIDENCE.md](EVIDENCE.md). If a line here disagrees with STORY.md, STORY.md wins: change it there first. The 5-minute judging talk is in [PITCH.md](PITCH.md).

**Rules**
- The two controller-off/on numbers are **$10,285** and **$0**. Don't round them differently, and don't show or say $1,824: that figure is from before rescoring.
- Never call a block a catch unless the card shows a rule. A fail-safe block, when blue is unreachable, is labelled as one.
- Every shot is a recording or a finished run, so every take comes out the same. Nothing has to be live while you record.

## Line by line

About 215 words of voiceover, at about 145 words a minute.

| Time | On screen | Voiceover (word for word) |
|---|---|---|
| 0:00–0:12 | Black. Text cards fade in: "Arup · Hong Kong · 2024", then "HK$200,000,000". | "In 2024, a finance worker at Arup joined a video call with his CFO. Every face on that call was a deepfake. He sent twenty-five million dollars." |
| 0:12–0:20 | Text card: "Fraud gets past whoever approves the payment." Then: "That job is going to AI agents." | "Fraud like this works by getting past whoever approves the payment. And that job is going to AI agents." |
| 0:20–0:33 | The arena: the company and its three agents, each labelled as it's named. | "Red Ledger is the crash test. A live AI fraud agent attacks a company's books. An AI clerk pays the bills. And a controller rules on every payment before it moves." |
| 0:33–0:50 | Red's console asks to change a vendor's bank account. Cut to blue's console: the **ESCALATE** card. Zoom on "Needs independent verification: destination change overlaps open invoices." | "Red asks to change a vendor's bank account. That's the move that took a hundred and twenty million dollars from Google and Facebook. The clerk would approve it. But the ledger asks the controller first, and the change is held until someone verifies it." |
| 0:50–1:03 | Compare card, "Real run" tab: controller off vs on, same seed. | "Same company, same ten days. Controller off: that one swap cost ten thousand dollars. Controller on: zero." |
| 1:03–1:20 | Evolution card for ln_f52a3df83c8d climbing from $19k to $98k, then the card for ln_431bf702e8a0 at $0. | "Then we let red learn. Over five generations it found that invoices split just under the approval limit got paid, and it climbed to ninety-eight thousand dollars. None of our controls caught it. We closed the gap in the ledger, and the next live run stole nothing." |
| 1:20–1:30 | Title card: "Red Ledger", then "app.redledger.us · github.com/…". | "Before your agent gets the checkbook, crash-test it. Red Ledger." |

## Voiceover only (to read while recording)

**0:00–0:12** In 2024, a finance worker at Arup joined a video call with his CFO. Every face on that call was a deepfake. He sent twenty-five million dollars.

**0:12–0:20** Fraud like this works by getting past whoever approves the payment. And that job is going to AI agents.

**0:20–0:33** Red Ledger is the crash test. A live AI fraud agent attacks a company's books. An AI clerk pays the bills. And a controller rules on every payment before it moves.

**0:33–0:50** Red asks to change a vendor's bank account. That's the move that took a hundred and twenty million dollars from Google and Facebook. The clerk would approve it. But the ledger asks the controller first, and the change is held until someone verifies it.

**0:50–1:03** Same company, same ten days. Controller off: that one swap cost ten thousand dollars. Controller on: zero.

**1:03–1:20** Then we let red learn. Over five generations it found that invoices split just under the approval limit got paid, and it climbed to ninety-eight thousand dollars. None of our controls caught it. We closed the gap in the ledger, and the next live run stole nothing.

**1:20–1:30** Before your agent gets the checkbook, crash-test it. Red Ledger.

## Where each shot comes from

| Time | Source |
|---|---|
| 0:00–0:20 | Text cards made in the editor. |
| 0:20–0:33 | The arena at `app.redledger.us` (or `NEXT_PUBLIC_MOCK=true` locally). The show (`S`, or `?show=recorded`) gives a paced walkthrough of the three agents; if you use it, keep its RECORDED label in frame. |
| 0:33–0:50 | Red's and blue's consoles replaying the controller-on run: `/backstage/red?replay=1` and `/backstage/blue?replay=1` (admin login at `/admin` first). They replay `recordings/demo-enforce-live.jsonl`, where red's bank-account swap is escalated with "Needs independent verification: destination change overlaps open invoices." If the console text is too dense for video, show the same escalation as the arena's verdict card instead. |
| 0:50–1:03 | Compare card, **Real run** tab (the recorded live-red pair, seed 42, 10 days). It must show $0 for controller on. If it still shows $1,824, the site fix hasn't deployed yet, so record this shot after it has. |
| 1:03–1:20 | Evolution card: `app.redledger.us/?lineage=ln_f52a3df83c8d` (red climbs from $19k to $98k a generation), then `?lineage=ln_431bf702e8a0` (after the split rule: $0 in all three generations). The first card's per-attack chips can add up to more than the total; frame the total. |
| 1:20–1:30 | Title card. |

## Longer cut (optional)

Atlassian allows up to 3 minutes. For a longer cut, add 0:30 after 1:20: the controls report (`/report/<ep>`) and the audit log ("every action, with its inputs and its reason"). Otherwise the same 90-second video goes to every track.
