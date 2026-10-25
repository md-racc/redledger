# Voice: speak any fraud scheme, in any language

In the attack console, under the eight scheme tiles, a judge can **say a fraud scheme in their own words** (or type it) and watch the
controls deal with it. Any language: the speech is transcribed by ElevenLabs speech-to-text, which detects the language itself.

```
mic → browser (16 kHz mono WAV) → POST /api/voice/transcribe → ElevenLabs /v1/speech-to-text → { text, language }
   → the box in the console (editable) → Launch it
   → POST /api/bf/inputs {target: red, payload: {kind: "custom_fraud_scheme", text, language, closest_built_in}}   (red's next turn)
   → POST /api/bf/episodes/{id}/attack {scheme_id: <closest built-in>}                                           (what actually runs)
```

## What is real and what is not (read this before you say it on stage)

- **Transcription and language detection are real** (ElevenLabs Scribe), in whatever language is spoken.
- **Red reads the exact words** (battlefield `POST /inputs`, which arrives in red's next turn as `options.inputs`; red's side is #165,
  `red/agent.py` `judge_block`). The words go into red's prompt as quoted data (up to 500 characters of each of the last three
  requests, with the language and the scheme the console matched), never as instructions. **The console always forces the closest of
  red's eight schemes**, and on a forced turn red uses the words only to set that scheme's params (amounts, counts). Only on an
  unforced turn would red choose the scheme from the words. `run_scheme` takes catalog ids only, so red can never run something
  outside its eight: ghost vendor, bank swap, duplicate invoice, threshold split, ghost employee, expense inflation, PO mismatch, amount
  drift. The console says so ("Red reads your exact words to set the amount and details. The scheme that runs is the closest of its
  eight").
- **"Closest" is a keyword match** (`lib/voice/intent.ts`): phrases in about a dozen languages (English, Spanish, Portuguese, French, Italian, German, Dutch, Chinese, Japanese, Korean, Arabic, Hindi, Russian, Turkish) for the eight schemes, visible and
  changeable in a dropdown. It is not a translator or an LLM. An unfamiliar phrasing in an unfamiliar language says "no clear match: pick one".
  A test keeps its eight schemes the same as the arena roster's.
- So **do not say "red invents any scheme you describe"**. Say: "describe it in your own words; red reads them, and runs the closest of
  its eight schemes with your details." Whether red's three newest schemes (#166) have been run live is not something this feature
  shows; the numbers in the pitch come from the first five.

## How it listens

- **Speak, then pause.** Once someone has talked (three readings in a row above a small level) and then been quiet for 1.6 s, the
  recording ends by itself and is sent (`lib/voice/vad.ts`, tested without a microphone). The Stop button, and a 45 s limit,
  still work. In a loud room the level never drops, so it never ends by itself: press Stop.
- **Nobody talked.** If no speech is heard for 9 s the recording is thrown away, nothing is sent (no credits spent on silence) and
  the console says "I did not hear anyone".
- **Try saying.** With the box empty, four chips (English, Spanish, German, Hindi) fill it with a ready sentence. Each one is
  checked against the matcher in a test, so the scheme a chip promises is the scheme the console picks. They are also the way in
  when there is no microphone or no key.
- **Enter launches** what is in the box (not while an input method is composing, so Japanese and Chinese typing still works).
- The matcher ignores accents (`nomina` finds `nómina`; kana, Hangul and Devanagari are left alone) and, on an equal number of
  matched phrases, leans to the scheme whose phrases cover more of what was said (still shown as "no clear match: pick one").

## Setup

Server-only environment (the browser never sees the key; `frontend/.env.example`):

| Variable | Meaning |
|---|---|
| `ELEVENLABS_API_KEY` | the speech-to-text key. Unset: the console says voice is not set up and typing still works |
| `ELEVENLABS_STT_MODEL` | optional, default `scribe_v2` |
| `ELEVENLABS_API_BASE` | optional, default `https://api.elevenlabs.io` (regional endpoints; a test stub) |

Locally: put it in `frontend/.env.local`. In production Ad has wired it (GitHub secret `ELEVENLABS_API_KEY` → `deploy/render-env.sh` →
compose → the `frontend` container, README §11, vendor approved 2026-10-25). There is no way to read the secret back out of GitHub,
so a local run needs its own copy of the key.

## Cost and abuse

Every request spends the owner's credits. **Only admins can use it** (`lib/admin.ts`): the site is public, so a viewer's POST is
refused with `403 {"error":"viewer"}` before the key is touched, and the console disables the microphone for a viewer
(`useRole()`). The route also refuses cross-site posts, is behind the same Cloudflare Access check as the rest
of the site (`middleware.ts`), caps audio at 3 MB (about 90 s), the console stops listening at 45 s, and the route answers 429 after 20
requests a minute per server process. Audio is sent to ElevenLabs and not stored by us.

## Browser notes

The microphone needs `https` or `localhost`. The recording is decoded in the browser and resampled to 16 kHz mono 16-bit PCM WAV
(`lib/voice/recorder.ts`, `lib/voice/wav.ts`) so the format sent is the same on every browser and always one ElevenLabs accepts. The
button says what is wrong when the microphone is blocked or missing, and the box always works for typing.

## Files

`app/api/voice/transcribe/route.ts` (the route), `lib/voice/transcribe.ts` (the ElevenLabs call, error codes, messages),
`lib/voice/intent.ts` (closest scheme), `lib/voice/recorder.ts` and `wav.ts` (the browser side), `components/arena/useVoice.ts` (the
state), `components/arena/overlays/ThreatConsole.tsx` (the UI), `lib/arena/useFeed.ts` (`launchAttack(scheme, spoken)`). Tests:
`lib/voice/*.test.ts`. The stand-in battlefield (`tools/fake-battlefield.mjs`) accepts `POST /api/inputs` and keeps what it is given.
