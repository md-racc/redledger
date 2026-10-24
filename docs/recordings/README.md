# Demo recordings

The stage fallback: the controller-off and controller-on demo pair (README §14), recorded on prod on 2026-10-24 with red live on Droid (`gpt-5.4-mini`, reasoning `low`). Green and blue ran keyless. Both runs use seed 42 and 10 days.

| file | episode | mode | attacks launched / caught | extracted | false-positive cost | red credits |
|---|---|---|---|---|---|---|
| `demo-off-live.jsonl` | `ep_7f473df2a138` | `off` | 10 / 0 | $10,284.61 | $0 | 26,230 |
| `demo-enforce-live.jsonl` | `ep_540353ebf616` | `enforce` | 10 / 1 | $1,824.22 | $100 | 24,449 |

Each line is one event from the operator stream (`contracts/events.md`), exported with `make prod-record` and secret-scanned. The long hex strings are Droid tool-call ids. These are operator streams, so `attack.launched` events identify red's entities. Never feed them to an agent.

To replay one: copy it into `battlefield/fixtures/episodes/` (or the frontend's mocks) and use the replay route (`POST /replays/{id}/play`).
