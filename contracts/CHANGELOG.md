# Contracts changelog

Every change to anything in `contracts/` gets an entry here, in the same PR. Newest first.
Format: date · author · which file(s) · what changed · who was pinged.

Also record **Findings**: empirical answers to questions the docs left open (Droid SDK behavior,
sponsor API quirks). A finding is a contract too: once recorded, code relies on it.

## Findings

- 2026-10-23 · Ad · **Droid CLI install works in `python:3.11-slim`.** Proved by deploy run
  40050204221 (`gh run view 40050204221 --log`, job `build (red …)`): "Factory CLI v0.248.0
  installed successfully to /root/.local/bin/droid", and `droid-sdk==0.5.0` resolved via
  `agentkit[droid]`. Details from reading the installer script:
  `curl -fsSL https://app.factory.ai/cli | sh` is the documented Linux line (docs.factory.ai CLI
  quickstart). Proved by `curl -fsSL https://app.factory.ai/cli -o install.sh` and reading it: it
  needs only `curl` + `sha256sum`, installs to `$HOME/.local/bin/droid` (already on the agent
  Dockerfiles' PATH), and hardcodes the version it fetches (v0.248.0 today), so rebuilds drift
  unless pinned (`droid update --version <v>` after install, or `npm install -g droid@<v>`). It
  picks the AVX2 vs `-baseline` binary from the *build* host's CPU. The `|| echo WARN` in the
  agent Dockerfiles hides a failed install (owners Al/M may want it removed now that it works).
- Still open:
  - Does `Autonomy.OFF` raise a permission request for every MCP tool call? (green dev, Fri night)
  - Exact tool ID string for in-process MCP tools as seen by `session.list_tools()` (any agent dev)
  - Does `comment=` on a `CANCEL` reach the model as the rejection reason? (green dev)

## Changes

- 2026-10-23 · Ad · agent-service.md, ledger-api.yaml, events.md · split INTERNAL_TOKEN into AGENT_TOKEN/OPERATOR_TOKEN, POST /ws/ticket, GET /events operator-only, credit_guard error · all

- 2026-10-23 · adi · schema.sql (agent_state, inputs), events.md (x.* namespace), agent-service.md (options.inputs, extension points), ledger-api.yaml (state/inputs/query) · extension points · all

- 2026-10-23 · adi · schema.sql, ledger-api.yaml, events.md, agent-service.md · initial contracts · all
