# Development history

This directory preserves the project's build history:

- [DEVLOG.md](DEVLOG.md): the early hackathon log, frozen in its original form.
- [devlog/](devlog/): dated fragments from later hackathon and maintenance work.

The historical log and dated fragments were moved without changing their contents. Paths and
instructions inside them describe the repository at the time; use [the current maintenance
guide](../CONTRIBUTING.md) and [operations guide](../OPERATIONS.md) for current instructions.

From the repository root, `make devlog-show` prints the combined log. New maintenance notes
are optional; `make devlog WHO=Ad MSG="..." SLUG=topic` writes to `docs/history/devlog/`.
