# Contracts changelog

Every change to anything in `contracts/` gets an entry here, in the same PR. Newest first.
Format: date · author · which file(s) · what changed · who was pinged.

Also record **Findings**: empirical answers to questions the docs left open (Droid SDK behavior,
sponsor API quirks). A finding is a contract too: once recorded, code relies on it.

## Findings

- 2026-10-23 · Al · Python `droid-sdk` exists on PyPI: `droid-sdk==0.5.0`, extra `[mcp]` (`uv pip install "droid-sdk[mcp]"`). Exposes everything `agentkit.droid_agent` imports: `Autonomy{OFF,LOW,MEDIUM,HIGH}`, `Session(model=, config=, interactions=, api_key=)`, `SessionConfig(autonomy=, mcp_servers=, disable_builtin_skills=, system_prompt=, restrict_tools=, …)`, `InteractionHandlers`, `TextDelta/ThinkingDelta/ToolCall/ToolResult`, `droid_sdk.mcp.create_sdk_mcp_server(name, tools, version)` + `tool(name, description, fn)`. `SessionConfig.system_prompt` accepts a plain `str` (type is `str | SystemPromptPreset`). `Session.stream(prompt, *, timeout=, include_partial_messages=)` matches agentkit's call. Proved with `python -c "import inspect, droid_sdk; print(inspect.signature(droid_sdk.SessionConfig))"`.
- 2026-10-23 · Al · Permission handler sees MCP tool arguments: `droid_sdk.permissions.McpToolAction` has `tool_use: ToolUseBlock` with fields `{id, name, input: Mapping[str, object], thought_signature}`, plus `tool_name`, `actual_tool_name`, `server_name`, `impact_level`. So green's mirror (`action.tool_use.input`, `action.tool_use.id`) is supported by the SDK types. (The TypeScript SDK's `permissionHandler` does NOT expose arguments for MCP tools; irrelevant here since we use Python.) Still unverified at runtime: whether `Autonomy.OFF` raises a permission request for every in-process MCP tool call, and whether `comment=` on `CANCEL` reaches the model.
- 2026-10-23 · Al · Tooling: `uv sync` fails in every service dir ("agentkit is included as a workspace member, but references a path in tool.uv.sources") because `battlefield/pyproject.toml` and `red/pyproject.toml` use `agentkit = { path = "../agentkit" }` while the root `pyproject.toml` declares a uv workspace. Fix (Ad): change those sources to `agentkit = { workspace = true }`. Workaround used meanwhile: `cd red && uv venv -p 3.11 .venv && uv pip install -p .venv/bin/python -e ../agentkit pytest pytest-asyncio respx ruff fastapi "uvicorn[standard]" httpx pydantic structlog`, then `.venv/bin/python -m pytest -q`.
- Still open:
  - Does `Autonomy.OFF` raise a permission request for every MCP tool call? (green dev, Fri night)
  - Exact tool ID string for in-process MCP tools as seen by `session.list_tools()` (any agent dev)
  - Does `comment=` on a `CANCEL` reach the model as the rejection reason? (green dev)
  - Droid CLI install command that works in `python:3.11-slim` (backend)

## Changes

- 2026-10-23 · adi · schema.sql (agent_state, inputs), events.md (x.* namespace), agent-service.md (options.inputs, extension points), ledger-api.yaml (state/inputs/query) · extension points · all

- 2026-10-23 · adi · schema.sql, ledger-api.yaml, events.md, agent-service.md · initial contracts · all
