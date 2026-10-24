# devlog/ — one fragment per PR

Each PR adds exactly one file here, `devlog/<YYYY-MM-DDTHHMMZ>-<who>-<slug>.md`, holding one
line in the `DEVLOG.md` format:

```
- 2026-10-24T03:10Z · Al · red: ghost_vendor + bank_swap landing against mock battlefield; next: threshold_split; blocked: none
```

- Write it with `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …" [SLUG=topic]`
  (SLUG defaults to your branch's topic).
- Read the whole log with `make devlog-show` (`DEVLOG.md` history + these fragments, oldest first).
- Never edit or delete another person's fragment. New files never conflict, so no resync for devlog.
- Rules: `GIT.md` §6.
