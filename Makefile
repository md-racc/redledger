# Red Ledger — one Makefile for every branch. Owner: Dev Ad.
# Every dev runs the same targets; CI runs `make lint test`.
SHELL := /bin/bash
COMPOSE := docker compose
DEV := -f docker-compose.yml -f docker-compose.dev.yml
MOCK := -f docker-compose.yml -f docker-compose.mock.yml
API ?= http://localhost:8000
# Operator-scope token for the curl targets. Reads OPERATOR_TOKEN from .env, then the legacy
# INTERNAL_TOKEN (stale local .env files), then the compose default. Quotes are stripped because
# deploy/render-env.sh writes NAME='value'.
env_get = $(shell grep -E '^$(1)=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "'\"")
TOKEN ?= $(call env_get,OPERATOR_TOKEN)
TOKEN := $(if $(TOKEN),$(TOKEN),$(call env_get,INTERNAL_TOKEN))
TOKEN := $(if $(TOKEN),$(TOKEN),change-me)
AUTH := -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json"

.PHONY: help up up-dry mock-agents down logs ps db-reset db-shell seed episode step toggle attack escalations score record replay \
        install lint fmt test test-agentkit test-battlefield test-red test-green test-blue test-frontend schema-dump devlog

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------- stack ----------
up: ## full stack, agents live (needs FACTORY_API_KEY)
	$(COMPOSE) up --build -d
up-dry: ## full stack, agents in DRY_RUN with hot reload
	$(COMPOSE) $(DEV) up --build -d
mock-agents: ## battlefield + postgres + stub agents (no LLMs). Agent devs: run your own service on top.
	$(COMPOSE) $(MOCK) up --build -d postgres battlefield red green blue
down: ## stop everything
	$(COMPOSE) $(DEV) $(MOCK) down --remove-orphans
logs: ## tail all logs (SVC=red to filter)
	$(COMPOSE) logs -f $(SVC)
ps:
	$(COMPOSE) ps
db-reset: ## wipe the database volume (schema re-applies on next start)
	$(COMPOSE) down -v --remove-orphans
db-shell: ## psql into the running db
	$(COMPOSE) exec postgres psql -U redledger redledger

# ---------- episode control (curl against battlefield) ----------
MODE ?= shadow
DAYS ?= 10
SEED ?= 42
episode: ## create + start an episode: make episode MODE=enforce SEED=42 DAYS=10
	@curl -s $(AUTH) -X POST $(API)/api/episodes -d '{"controller_mode":"$(MODE)","seed":$(SEED),"days":$(DAYS)}' | tee /tmp/rl_ep.json; echo
	@EP=$$(python3 -c 'import json;print(json.load(open("/tmp/rl_ep.json"))["id"])'); echo "episode $$EP"; \
	 curl -s $(AUTH) -X POST $(API)/api/episodes/$$EP/start; echo; echo "export EP=$$EP"
step: ## run one day of $(EP)
	curl -s $(AUTH) -X POST $(API)/api/episodes/$(EP)/step; echo
toggle: ## set controller mode on $(EP): make toggle EP=... MODE=enforce
	curl -s $(AUTH) -X PATCH $(API)/api/episodes/$(EP)/controller -d '{"mode":"$(MODE)"}'; echo
attack: ## force a scheme on next red turn: make attack EP=... SCHEME=ghost_vendor
	curl -s $(AUTH) -X POST $(API)/api/episodes/$(EP)/attack -d '{"scheme_id":"$(SCHEME)"}'; echo
escalations: ## list open escalations
	curl -s $(AUTH) "$(API)/api/escalations?status=open"; echo
score: ## score for $(EP)
	curl -s $(AUTH) $(API)/api/episodes/$(EP)/score; echo
record: ## dump $(EP) events to battlefield/fixtures/episodes/$(EP).jsonl
	curl -s $(AUTH) "$(API)/api/events?episode_id=$(EP)&limit=5000" | python3 -c 'import sys,json; [print(json.dumps(e)) for e in json.load(sys.stdin)]' > battlefield/fixtures/episodes/$(EP).jsonl
	@wc -l battlefield/fixtures/episodes/$(EP).jsonl
replay: ## stream a fixture to connected UIs: make replay FILE=ep_abc SPEED=4
	curl -s $(AUTH) -X POST $(API)/api/replays/$(FILE)/play -d '{"speed":$(or $(SPEED),4)}'; echo

# ---------- dev tooling ----------
install: ## install python deps for all services + frontend
	cd agentkit && uv sync --extra dev
	cd battlefield && uv sync --extra dev
	cd red && uv sync --extra dev
	cd green && uv sync --extra dev
	cd blue && uv sync --extra dev
	cd frontend && npm install
lint: ## ruff + tsc
	uvx ruff check agentkit battlefield red green blue
	uvx ruff format --check agentkit battlefield red green blue
	cd frontend && npm run typecheck
fmt: ## auto-format
	uvx ruff format agentkit battlefield red green blue
	uvx ruff check --fix agentkit battlefield red green blue
	cd frontend && npm run format
test: test-agentkit test-battlefield test-red test-green test-blue test-frontend ## all tests
test-agentkit:
	cd agentkit && uv run pytest -q
test-battlefield:
	cd battlefield && uv run pytest -q
test-red:
	cd red && uv run pytest -q
test-green:
	cd green && uv run pytest -q
test-blue:
	cd blue && uv run pytest -q
test-frontend:
	cd frontend && npm test --silent
schema-dump: ## copy canonical schema into battlefield/db (for local non-docker runs)
	cp contracts/schema.sql battlefield/db/schema.sql && rm -rf battlefield/db/ext && cp -r contracts/ext battlefield/db/ext
devlog: ## append a DEVLOG entry: make devlog WHO=Ad MSG="..."
	@printf -- "- %s · %s · %s\n" "$$(date -u +%Y-%m-%dT%H:%MZ)" "$(WHO)" "$(MSG)" >> DEVLOG.md && tail -1 DEVLOG.md
