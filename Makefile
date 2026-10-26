# Red Ledger — one Makefile for every branch. Owner: Dev Ad.
# Every dev runs the same targets; CI runs `make lint test`.
SHELL := /bin/bash
# GNU make exports command-line variables into the environment of every recipe AND of every
# $(shell ...), and EXPANDS them to do so: `make help EP='$(shell touch x)'` would run `touch x`
# on your machine. So the user-input variables are never exported; targets that need one pass it
# explicitly (prod-*, devlog below). This must stay above the first $(shell ...) (env_get/TOKEN).
# Defaults for the local episode targets. Must precede `unexport` below: GNU make 4.4 `unexport`
# defines the names (empty), after which `?=` would be a no-op. Prod targets ignore these (prodarg).
MODE ?= shadow
DAYS ?= 10
SEED ?= 42
unexport EP MODE SEED DAYS PLAN SCHEME PARAMS SVC ESC DECISION NAME WHO MSG SLUG LN GENS REVEAL_DAYS REVEAL_GENERATIONS MAX_CREDITS GEN AGENTS RED GREEN BLUE RESET CONFIRM
# Keep build contexts, bind mounts, .env lookup and the project name rooted here.
COMPOSE := docker compose --project-directory . -f deploy/compose/docker-compose.yml
DEV := -f deploy/compose/docker-compose.dev.yml
MOCK := -f deploy/compose/docker-compose.mock.yml
API ?= http://localhost:8000
# Operator-scope token for the curl targets. Reads OPERATOR_TOKEN from .env, else the compose
# default `change-me`. No INTERNAL_TOKEN fallback: compose's battlefield doesn't read it, so a
# stale .env with only INTERNAL_TOKEN would send a token battlefield never sees (401). Quotes are
# stripped because deploy/render-env.sh writes NAME='value'.
env_get = $(shell grep -E '^$(1)=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "'\"")
# While `make local-stack` is up, its generated operator token (.local-stack/env) wins over .env.
LOCAL_STACK_TOKEN = $(shell grep -E '^OPERATOR_TOKEN=' .local-stack/env 2>/dev/null | tail -n 1 | cut -d= -f2-)
TOKEN ?= $(if $(wildcard .local-stack/pids/battlefield),$(LOCAL_STACK_TOKEN),$(call env_get,OPERATOR_TOKEN))
TOKEN := $(if $(TOKEN),$(TOKEN),change-me)
AUTH := -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json"
# `make evolve` defaults follow the lineage config (docs/ARCHITECTURE.md, Evolution), not the episode
# targets': MODE/DAYS count only when given on the command line.
LN_MODE = $(if $(filter command line,$(origin MODE)),$(MODE),enforce)
LN_DAYS = $(if $(filter command line,$(origin DAYS)),$(DAYS),6)

.PHONY: help up up-dry mock-agents down logs ps db-reset db-shell episode step toggle attack escalations score record replay \
        local-stack local-stack-status local-stack-stop \
        evolve lineage-status lineage-pause lineage-resume evolution-report lineage-export fixtures \
        prod-health prod-ps prod-logs prod-episode prod-step prod-pause prod-resume prod-toggle prod-attack prod-escalations \
        prod-resolve prod-score prod-wait prod-record prod-credits prod-fixtures prod-crs-episode \
        prod-evolve prod-lineage-status prod-lineage-pause prod-lineage-resume prod-lineage-wait prod-lineage-export prod-evolution-report \
        install lint fmt test test-agentkit test-battlefield test-red test-green test-blue test-frontend schema-dump devlog devlog-show

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

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

# ---------- local stack without docker: pgserver Postgres 16 + battlefield + agents as processes ----------
# State in .local-stack/ (self-ignoring). Mixed mode: real blue on top of mock red/green = BLUE=real.
# Real agents run DRY_RUN=true unless you export DRY_RUN=false or DRY_RUN_<AGENT>=false; FACTORY_API_KEY,
# DROID_MODEL_<AGENT> and CRS_* come from your own shell environment (never from a .env file).
local-stack: export LS_AGENTS := $(value AGENTS)
local-stack: export LS_RED := $(value RED)
local-stack: export LS_GREEN := $(value GREEN)
local-stack: export LS_BLUE := $(value BLUE)
local-stack: ## start the stack without docker: make local-stack [AGENTS=mock|real] [RED=|GREEN=|BLUE=mock|real]
	@AGENTS="$$LS_AGENTS" RED="$$LS_RED" GREEN="$$LS_GREEN" BLUE="$$LS_BLUE" battlefield/scripts/local_stack.sh up
local-stack-status: ## health of the local stack's processes
	@battlefield/scripts/local_stack.sh status
local-stack-stop: export LS_RESET := $(value RESET)
local-stack-stop: export LS_CONFIRM := $(value CONFIRM)
local-stack-stop: ## stop the local stack (RESET=1 CONFIRM=yes also wipes its database)
	@RESET="$$LS_RESET" CONFIRM="$$LS_CONFIRM" battlefield/scripts/local_stack.sh stop

# ---------- episode control (curl against battlefield) ----------
episode: ## create + start an episode: make episode MODE=enforce SEED=42 DAYS=10
	@curl -s $(AUTH) -X POST $(API)/api/episodes -d '{"controller_mode":"$(MODE)","seed":$(SEED),"days":$(DAYS)}' | tee /tmp/rl_ep.json; echo
	@EP=$$(python3 -c 'import json;print(json.load(open("/tmp/rl_ep.json"))["id"])'); echo "episode $$EP"; \
	 curl -s $(AUTH) -X POST $(API)/api/episodes/$$EP/start; echo; echo "export EP=$$EP"
fixtures: ## seed operator fixtures into $(EP) from a JSON $(FILE): make fixtures EP=... FILE=personas.json
	@test -n "$(EP)" -a -f "$(FILE)" || { echo "usage: make fixtures EP=<episode> FILE=<json>"; exit 2; }
	@curl -s $(AUTH) -X POST $(API)/api/episodes/$(EP)/fixtures --data-binary @"$(FILE)"; echo
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

# ---------- lineages: headless generations (docs/ARCHITECTURE.md, Evolution) ----------
evolve: ## create + start a headless lineage: make evolve GENS=3 DAYS=6 MODE=enforce SEED=42 REVEAL_DAYS=3 REVEAL_GENERATIONS=2
	@LN=$$(curl -s $(AUTH) -X POST $(API)/api/lineages -d '{"base_seed":$(SEED),"config":{"generations":$(or $(GENS),3),"days":$(LN_DAYS),"controller_mode":"$(LN_MODE)","reveal_days":$(or $(REVEAL_DAYS),3),"reveal_generations":$(or $(REVEAL_GENERATIONS),2)}}' \
	   | tee /dev/stderr | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])') || exit 1; echo; echo "lineage $$LN"; \
	 curl -s $(AUTH) -X POST $(API)/api/lineages/$$LN/start; echo; echo "export LN=$$LN"
lineage-status: ## generations, scores and playbook versions of $(LN)
	curl -s $(AUTH) $(API)/api/lineages/$(LN); echo
lineage-pause: ## pause $(LN) (its running generation pauses too)
	curl -s $(AUTH) -X POST $(API)/api/lineages/$(LN)/pause; echo
lineage-resume: ## resume $(LN) at the same generation
	curl -s $(AUTH) -X POST $(API)/api/lineages/$(LN)/resume; echo
evolution-report: ## runs/$(LN)/report.json + report.md (secret-scanned; partial while $(LN) runs)
	@API='$(API)' TOKEN='$(TOKEN)' python3 battlefield/scripts/evolution_report.py report '$(LN)'
lineage-export: ## log bundle runs/$(LN)/{lineage.json,playbooks/,gen-<g>/...} (contains origin: never commit)
	@API='$(API)' TOKEN='$(TOKEN)' python3 battlefield/scripts/evolution_report.py export '$(LN)'

# ---------- prod operator (runs ON the VM over ssh; OPERATOR_TOKEN never leaves the VM) ----------
# Thin wrappers over deploy/prod.sh; guide: docs/OPERATIONS.md. Host/key/timeouts: PROD_* env vars
# (see the script header). User values reach the script as PRODARG_* environment variables holding
# the raw text ($(value ...): make does not evaluate `$(...)` in them; the user variables themselves
# are unexported above), so JSON arrives exactly as typed:
#   make prod-episode MODE=enforce SEED=42 DAYS=10 PLAN='[{"day":2,"scheme_id":"bank_swap"}]'
#   make prod-attack EP=ep_123 SCHEME=ghost_vendor PARAMS='{"amount":4999}'
# Only values you actually give (command line or environment) are passed: the MODE/SEED/DAYS
# defaults above are for the local targets and never reach prod, so a bare `make prod-episode`
# fails with usage instead of starting a paid episode.
# Self-check: docs/OPERATIONS.md "Operate prod" (a $(shell) canary in EP).
PROD := deploy/prod.sh
prodarg = $(if $(filter command line environment,$(origin $(1))),$(value $(1)))
prod-%: export PRODARG_EP := $(call prodarg,EP)
prod-%: export PRODARG_MODE := $(call prodarg,MODE)
prod-%: export PRODARG_SEED := $(call prodarg,SEED)
prod-%: export PRODARG_DAYS := $(call prodarg,DAYS)
prod-%: export PRODARG_PLAN := $(call prodarg,PLAN)
prod-%: export PRODARG_SCHEME := $(call prodarg,SCHEME)
prod-%: export PRODARG_PARAMS := $(call prodarg,PARAMS)
prod-%: export PRODARG_SVC := $(call prodarg,SVC)
prod-%: export PRODARG_ESC := $(call prodarg,ESC)
prod-%: export PRODARG_DECISION := $(call prodarg,DECISION)
prod-%: export PRODARG_NAME := $(call prodarg,NAME)
prod-%: export PRODARG_LN := $(call prodarg,LN)
prod-%: export PRODARG_GENS := $(call prodarg,GENS)
prod-%: export PRODARG_REVEAL_DAYS := $(call prodarg,REVEAL_DAYS)
prod-%: export PRODARG_REVEAL_GENERATIONS := $(call prodarg,REVEAL_GENERATIONS)
prod-%: export PRODARG_MAX_CREDITS := $(call prodarg,MAX_CREDITS)
prod-%: export PRODARG_GEN := $(call prodarg,GEN)
prod-%: export PRODARG_FILE := $(call prodarg,FILE)
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
prod-fixtures: ## prod: seed operator fixtures (legit employees/expenses) into EP from a local JSON FILE
	@$(PROD) fixtures "$$PRODARG_EP" "$$PRODARG_FILE"
prod-crs-episode: ## prod: blue's CRS identity scenario, stepped, live audit: SEED=42 [DAYS=2]; prints a summary + PASS/FAIL
	@$(PROD) crs-episode "$$PRODARG_SEED" "$$PRODARG_DAYS"
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
prod-evolve: ## prod: create + start a lineage: GENS=3 DAYS=5 MODE=enforce SEED=42 MAX_CREDITS=1000000 [REVEAL_DAYS= REVEAL_GENERATIONS=]
	@$(PROD) evolve "$$PRODARG_GENS" "$$PRODARG_DAYS" "$$PRODARG_MODE" "$$PRODARG_SEED" "$$PRODARG_REVEAL_DAYS" "$$PRODARG_REVEAL_GENERATIONS" "$$PRODARG_MAX_CREDITS"
prod-lineage-status: ## prod: LN generations, scores, turn credits, current generation/day
	@$(PROD) lineage-status "$$PRODARG_LN"
prod-lineage-pause: ## prod: pause LN (and its running generation)
	@$(PROD) lineage-pause "$$PRODARG_LN"
prod-lineage-resume: ## prod: resume LN at the same generation (also lifts a lineage credit-cap pause)
	@$(PROD) lineage-resume "$$PRODARG_LN"
prod-lineage-wait: ## prod: poll LN until finished/failed/paused (PROD_LINEAGE_WAIT_TIMEOUT, default 7200 s)
	@$(PROD) lineage-wait "$$PRODARG_LN"
prod-lineage-export: ## prod: LN log bundle -> runs/<LN>/ [GEN=<g>] (secret-scanned; ground truth: never commit)
	@$(PROD) lineage-export "$$PRODARG_LN" "$$PRODARG_GEN"
prod-evolution-report: ## prod: LN report -> runs/<LN>/report.json + report.md (partial while it runs)
	@$(PROD) evolution-report "$$PRODARG_LN"

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
# Optional maintenance notes live alongside the preserved history; see docs/CONTRIBUTING.md.
# WHO/MSG/SLUG reach the shell via the environment as raw text ($(value ...); the variables
# themselves are unexported above), so a MSG like '$11,004 "quoted"' is written verbatim: make
# never expands `$1`, the shell never re-parses it.
devlog: export DEVLOG_WHO := $(value WHO)
devlog: export DEVLOG_MSG := $(value MSG)
devlog: export DEVLOG_SLUG := $(value SLUG)
devlog: ## write docs/history/devlog/<ts>-<who>-<slug>.md: make devlog WHO=Ad MSG="..." [SLUG=topic, default: branch topic]
	@set -euo pipefail; \
	 [ -n "$$DEVLOG_WHO" ] || { echo "devlog: WHO is required (Ad|Al|M|R)" >&2; exit 1; }; \
	 [ -n "$$DEVLOG_MSG" ] || { echo "devlog: MSG is required" >&2; exit 1; }; \
	 [[ "$$DEVLOG_WHO" =~ ^[A-Za-z][A-Za-z0-9_-]*$$ ]] || { echo "devlog: WHO must be a plain name (Ad|Al|M|R)" >&2; exit 1; }; \
	 slug="$$DEVLOG_SLUG"; \
	 if [ -z "$$slug" ]; then br="$$(git rev-parse --abbrev-ref HEAD)"; slug="$${br#*/}"; fi; \
	 slug="$$(printf '%s' "$$slug" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed -e 's/^-*//' -e 's/-*$$//')"; \
	 [ -n "$$slug" ] || { echo "devlog: could not derive SLUG; pass SLUG=topic" >&2; exit 1; }; \
	 now="$$(date -u +%Y-%m-%dT%H%M)"; \
	 f="docs/history/devlog/$${now}Z-$${DEVLOG_WHO}-$${slug}.md"; \
	 [ ! -e "$$f" ] || { echo "devlog: $$f already exists" >&2; exit 1; }; \
	 mkdir -p docs/history/devlog; \
	 msg="$$(printf '%s' "$$DEVLOG_MSG" | tr '\n' ' ')"; \
	 printf -- '- %s · %s · %s\n' "$${now:0:13}:$${now:13:2}Z" "$$DEVLOG_WHO" "$$msg" > "$$f"; \
	 echo "$$f"; cat "$$f"
devlog-show: ## print the combined log (docs/history/DEVLOG.md history + docs/history/devlog/ fragments), oldest first
	@shopt -s nullglob; \
	 { grep -h '^- [0-9]' docs/history/DEVLOG.md || true; for f in docs/history/devlog/[0-9]*.md; do grep -h '^- [0-9]' "$$f" || true; done; } \
	 | LC_ALL=C sort -s -k2,2
