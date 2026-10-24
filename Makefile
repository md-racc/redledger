# Red Ledger — one Makefile for every branch. Owner: Dev Ad.
# Every dev runs the same targets; CI runs `make lint test`.
SHELL := /bin/bash
COMPOSE := docker compose
DEV := -f docker-compose.yml -f docker-compose.dev.yml
MOCK := -f docker-compose.yml -f docker-compose.mock.yml
API ?= http://localhost:8000
# Operator-scope token for the curl targets. Reads OPERATOR_TOKEN from .env, else the compose
# default `change-me`. No INTERNAL_TOKEN fallback: compose's battlefield doesn't read it, so a
# stale .env with only INTERNAL_TOKEN would send a token battlefield never sees (401). Quotes are
# stripped because deploy/render-env.sh writes NAME='value'.
env_get = $(shell grep -E '^$(1)=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "'\"")
TOKEN ?= $(call env_get,OPERATOR_TOKEN)
TOKEN := $(if $(TOKEN),$(TOKEN),change-me)
AUTH := -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json"

.PHONY: help up up-dry mock-agents down logs ps db-reset db-shell seed episode step toggle attack escalations score record replay \
        prod-health prod-ps prod-logs prod-episode prod-step prod-pause prod-resume prod-toggle prod-attack prod-escalations \
        prod-resolve prod-score prod-wait prod-record prod-credits \
        install lint fmt test test-agentkit test-battlefield test-red test-green test-blue test-frontend schema-dump devlog devlog-show

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

# ---------- prod operator (runs ON the VM over ssh; OPERATOR_TOKEN never leaves the VM) ----------
# Thin wrappers over deploy/prod.sh; guide: deploy/PROD-OPS.md. Host/key/timeouts: PROD_* env vars
# (see the script header). As with `devlog`, user values reach the script through the environment,
# unexpanded ($(value ...)), so JSON is passed verbatim:
#   make prod-episode MODE=enforce SEED=42 DAYS=10 PLAN='[{"day":2,"scheme_id":"bank_swap"}]'
#   make prod-attack EP=ep_123 SCHEME=ghost_vendor PARAMS='{"amount":4999}'
PROD := deploy/prod.sh
prod-%: export PRODARG_EP := $(value EP)
prod-%: export PRODARG_MODE := $(value MODE)
prod-%: export PRODARG_SEED := $(value SEED)
prod-%: export PRODARG_DAYS := $(value DAYS)
prod-%: export PRODARG_PLAN := $(value PLAN)
prod-%: export PRODARG_SCHEME := $(value SCHEME)
prod-%: export PRODARG_PARAMS := $(value PARAMS)
prod-%: export PRODARG_SVC := $(value SVC)
prod-%: export PRODARG_ESC := $(value ESC)
prod-%: export PRODARG_DECISION := $(value DECISION)
prod-%: export PRODARG_NAME := $(value NAME)
prod-health: ## prod: battlefield /health (incl. agents), from inside the VM
	@$(PROD) health
prod-ps: ## prod: docker compose ps on the VM
	@$(PROD) ps
prod-logs: ## prod: last 200 log lines (SVC=red to filter)
	@$(PROD) logs "$$PRODARG_SVC"
prod-episode: ## prod: create + start: MODE=enforce SEED=42 DAYS=10 [PLAN='<json array>']
	@$(PROD) episode "$$PRODARG_MODE" "$$PRODARG_SEED" "$$PRODARG_DAYS" "$$PRODARG_PLAN"
prod-step: ## prod: run one day of EP (pause first)
	@$(PROD) step "$$PRODARG_EP"
prod-pause: ## prod: pause EP
	@$(PROD) pause "$$PRODARG_EP"
prod-resume: ## prod: resume EP (also re-arms the credit guard)
	@$(PROD) resume "$$PRODARG_EP"
prod-toggle: ## prod: set controller mode: EP=... MODE=off|shadow|enforce
	@$(PROD) toggle "$$PRODARG_EP" "$$PRODARG_MODE"
prod-attack: ## prod: force a scheme on next red turn: EP=... SCHEME=... [PARAMS='<json>']
	@$(PROD) attack "$$PRODARG_EP" "$$PRODARG_SCHEME" "$$PRODARG_PARAMS"
prod-escalations: ## prod: open escalations [EP=...]
	@$(PROD) escalations "$$PRODARG_EP"
prod-resolve: ## prod: resolve an escalation: ESC=... DECISION=approve|block
	@$(PROD) resolve "$$PRODARG_ESC" "$$PRODARG_DECISION"
prod-score: ## prod: score for EP
	@$(PROD) score "$$PRODARG_EP"
prod-wait: ## prod: poll EP until finished (PROD_WAIT_TIMEOUT, default 3600 s)
	@$(PROD) wait "$$PRODARG_EP"
prod-record: ## prod: EP events -> battlefield/fixtures/episodes/<NAME or EP>.jsonl, secret-scanned
	@$(PROD) record "$$PRODARG_EP" "$$PRODARG_NAME"
prod-credits: ## prod: factory_credits per agent/day for EP vs MAX_CREDITS_PER_EPISODE
	@$(PROD) credits "$$PRODARG_EP"

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
# devlog: one fragment file per PR, so PRs never conflict on DEVLOG.md (GIT.md §6).
# WHO/MSG/SLUG reach the shell via the environment, unexpanded ($(value ...)), so a MSG like
# '$11,004 "quoted"' is written verbatim: make never sees `$1`, the shell never re-parses it.
devlog: export DEVLOG_WHO := $(value WHO)
devlog: export DEVLOG_MSG := $(value MSG)
devlog: export DEVLOG_SLUG := $(value SLUG)
devlog: ## write devlog/<ts>-<who>-<slug>.md: make devlog WHO=Ad MSG="..." [SLUG=topic, default: branch topic]
	@set -euo pipefail; \
	 [ -n "$$DEVLOG_WHO" ] || { echo "devlog: WHO is required (Ad|Al|M|R)" >&2; exit 1; }; \
	 [ -n "$$DEVLOG_MSG" ] || { echo "devlog: MSG is required" >&2; exit 1; }; \
	 [[ "$$DEVLOG_WHO" =~ ^[A-Za-z][A-Za-z0-9_-]*$$ ]] || { echo "devlog: WHO must be a plain name (Ad|Al|M|R)" >&2; exit 1; }; \
	 slug="$$DEVLOG_SLUG"; \
	 if [ -z "$$slug" ]; then br="$$(git rev-parse --abbrev-ref HEAD)"; slug="$${br#*/}"; fi; \
	 slug="$$(printf '%s' "$$slug" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed -e 's/^-*//' -e 's/-*$$//')"; \
	 [ -n "$$slug" ] || { echo "devlog: could not derive SLUG; pass SLUG=topic" >&2; exit 1; }; \
	 now="$$(date -u +%Y-%m-%dT%H%M)"; \
	 f="devlog/$${now}Z-$${DEVLOG_WHO}-$${slug}.md"; \
	 [ ! -e "$$f" ] || { echo "devlog: $$f already exists" >&2; exit 1; }; \
	 mkdir -p devlog; \
	 msg="$$(printf '%s' "$$DEVLOG_MSG" | tr '\n' ' ')"; \
	 printf -- '- %s · %s · %s\n' "$${now:0:13}:$${now:13:2}Z" "$$DEVLOG_WHO" "$$msg" > "$$f"; \
	 echo "$$f"; cat "$$f"
devlog-show: ## print the combined log (DEVLOG.md history + devlog/ fragments), oldest first
	@shopt -s nullglob; \
	 { grep -h '^- [0-9]' DEVLOG.md || true; for f in devlog/[0-9]*.md; do grep -h '^- [0-9]' "$$f" || true; done; } \
	 | LC_ALL=C sort -s -k2,2
