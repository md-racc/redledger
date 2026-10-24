# Contracts changelog

Every change to anything in `contracts/` gets an entry here, in the same PR. Newest first.
Format: date · author · which file(s) · what changed · who was pinged.

Also record **Findings**: empirical answers to questions the docs left open (Droid SDK behavior,
sponsor API quirks). A finding is a contract too: once recorded, code relies on it.

## Findings

- (none yet) — first ones to record:
  - Does `Autonomy.OFF` raise a permission request for every MCP tool call? (green dev, Fri night)
  - Exact tool ID string for in-process MCP tools as seen by `session.list_tools()` (any agent dev)
  - Does `comment=` on a `CANCEL` reach the model as the rejection reason? (green dev)
  - Droid CLI install command that works in `python:3.11-slim` (backend)

## Changes

- 2026-10-23 · Ad · agent-service.md, ledger-api.yaml, events.md · split INTERNAL_TOKEN into AGENT_TOKEN/OPERATOR_TOKEN, POST /ws/ticket, GET /events operator-only, credit_guard error · all

- 2026-10-23 · adi · schema.sql (agent_state, inputs), events.md (x.* namespace), agent-service.md (options.inputs, extension points), ledger-api.yaml (state/inputs/query) · extension points · all

- 2026-10-23 · adi · schema.sql, ledger-api.yaml, events.md, agent-service.md · initial contracts · all
