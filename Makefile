# Agentic Project Intelligence POC: everyday commands (Step 03).
# Run `make help` for the list. Requires Docker, uv, pnpm and Node.
SHELL := /bin/bash
UV := env -u VIRTUAL_ENV uv
COMPOSE := docker compose

.PHONY: help env up down logs ps seed seed-policies seed-projects seed-users smoke-model config \
        install test test-contracts test-backend test-web lint typecheck check-step01 check-step02 check-step03 mutations-step03 \
        check-step04 mutations-step04 plan-queries eval-identity smoke-identity set-secret hooks

help: ## Show the available commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-17s %s\n", $$1, $$2}'

env: ## Create or complete .env (keeps your values, generates secrets)
	python3 scripts/init_env.py

hooks: ## Install the git pre-commit hook that blocks credentials from being committed
	printf '#!/bin/sh\nexec python3 scripts/check_no_secrets.py --staged\n' > .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed: scripts/check_no_secrets.py --staged"

set-secret: ## Store one credential in .env from a hidden prompt: make set-secret NAME=ANTHROPIC_API_KEY
	python3 scripts/set_env_secret.py $(NAME)

up: env ## Build and start MongoDB, API, worker, scheduler and web; waits until healthy
	$(COMPOSE) up -d --build --wait

down: ## Stop everything (database volume is kept)
	$(COMPOSE) down

ps: ## Show service status
	$(COMPOSE) ps -a

logs: ## Follow logs from all services
	$(COMPOSE) logs -f --tail=100

seed: seed-policies seed-projects seed-users ## Load source policies, the five projects and the seeded users

seed-policies: ## Load seed/source_policies.json into ai_source_policies (immutable versions; safe to repeat)
	$(COMPOSE) exec -T api python -m app.cli seed-policies

seed-projects: ## Load the five-project input file (safe to repeat)
	$(COMPOSE) exec -T api python -m app.cli seed-projects

seed-users: ## Create seeded users (password from SEED_USER_PASSWORD in .env, or asked for)
	$(COMPOSE) exec api python -m app.cli seed-users

smoke-model: ## One real Claude structured-output call, or "skipped" without a key
	$(COMPOSE) exec -T api python -m app.cli smoke-model

config: ## Show mode, model IDs and which credentials are present (names only)
	$(COMPOSE) exec -T api python -m app.cli check-config

install: ## Install local toolchains (backend, web, contract tooling)
	cd backend && $(UV) sync
	cd web && pnpm install --frozen-lockfile
	test -x .venv/bin/python || python3 -m venv .venv
	.venv/bin/pip install -q -r scripts/requirements.txt

test: test-contracts test-backend test-web ## Run every test suite (MongoDB must be up)

test-contracts: ## Step 01-02 contract and input tests
	.venv/bin/python -m unittest discover -s scripts/tests -q

test-backend: ## Backend tests against the running MongoDB replica set
	cd backend && $(UV) run pytest -q

test-web: ## Web unit tests
	cd web && pnpm test

lint: ## Lint backend and web
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check .
	cd web && pnpm lint

typecheck: ## Type-check backend and web; check generated API types are current
	cd backend && $(UV) run mypy
	cd web && pnpm typecheck && pnpm check:api

check-step01: ## Step 01 checks with a saved log
	bash scripts/run_step01_checks.sh

check-step02: ## Step 02 checks with a saved log
	bash scripts/run_step02_checks.sh

check-step03: ## Step 03 checks with a saved log
	bash scripts/run_step03_checks.sh

mutations-step03: ## Step 03 mutation check: each backend rule disabled must be caught (stack up)
	bash scripts/run_step03_mutations.sh

plan-queries: ## Bounded search queries for every project (approved aliases only)
	$(COMPOSE) exec -T api python -m app.cli plan-queries

eval-identity: ## Identity evaluation on the synthetic labelled set, saved to ai_evaluations
	$(COMPOSE) exec -T api python -m app.cli eval-identity --save

smoke-identity: ## Whole identity path on the fictional catalogue in a scratch database
	$(COMPOSE) exec -T api python -m app.cli fixture-smoke-identity

check-step04: ## Step 04 checks with a saved log
	bash scripts/run_step04_checks.sh

mutations-step04: ## Step 04 mutation check: each identity rule disabled must be caught (stack up)
	bash scripts/run_step04_mutations.sh
