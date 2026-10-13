#!/usr/bin/env bash
# Step 09.7 browser journeys: seed the journey database, start the API, a journeys-only worker and the web app on
# spare ports with the real environment (.env, live mode), run Playwright, stop everything.
#
#   scripts/run_step09_e2e.sh
#
# Needs the Compose MongoDB running (make up). Writes logs/step-09/e2e-<UTC time>.log. The journeys use the database
# sy_poc_e2e (dropped and reseeded each time), never sy_poc; they never start a run and generate content from reviews
# only, and the worker takes no collection, analysis or media job, so no paid provider is called.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$ROOT/logs/step-09/e2e-$STAMP.log"
mkdir -p "$ROOT/logs/step-09"
API_PORT=8100
WEB_PORT=3100
PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null; done
  wait 2>/dev/null
}
trap cleanup EXIT

log() { printf '%s\n' "$*" | tee -a "$LOG"; }

unset VIRTUAL_ENV
export MONGODB_DB=sy_poc_e2e
export WEB_INTERNAL_URL="http://localhost:$WEB_PORT"
export WORKER_ROLE=journeys
export E2E_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
# The shared revalidation secret from .env, for the web app (never printed).
REVALIDATION_SECRET="$(grep '^REVALIDATION_SECRET=' "$ROOT/.env" | cut -d= -f2-)"
export REVALIDATION_SECRET

log "=== Step 09 browser journeys, $STAMP (database $MONGODB_DB, real .env, live mode) ==="
cd "$ROOT/backend" || exit 1
SEED="$(uv run python -m tests.e2e_seed 2>>"$LOG" | tail -1)"
log "seed: $SEED"
E2E_PROJECT_ID="$(printf '%s' "$SEED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["project_id"])')" || exit 1
E2E_SLUG="$(printf '%s' "$SEED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["slug"])')" || exit 1
export E2E_PROJECT_ID E2E_SLUG

uv run uvicorn app.api.main:app --host 127.0.0.1 --port "$API_PORT" >>"$LOG" 2>&1 &
PIDS+=($!)
uv run python -m app.workers.worker >>"$LOG" 2>&1 &
PIDS+=($!)

cd "$ROOT/web" || exit 1
log "--- building the web app against the journey API"
API_INTERNAL_URL="http://localhost:$API_PORT" pnpm build >>"$LOG" 2>&1 || { log "web build failed"; exit 1; }
API_INTERNAL_URL="http://localhost:$API_PORT" PORT="$WEB_PORT" pnpm exec next start -p "$WEB_PORT" >>"$LOG" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -sf "http://localhost:$API_PORT/healthz" >/dev/null && curl -sf -o /dev/null "http://localhost:$WEB_PORT/console/login" && break
  sleep 2
done
MODE="$(curl -sf "http://localhost:$API_PORT/healthz" | python3 -c 'import json,sys; print(json.load(sys.stdin)["mode"])')"
log "API mode: $MODE"

log "--- Playwright"
E2E_BASE_URL="http://localhost:$WEB_PORT" pnpm exec playwright test 2>&1 | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}
if [ "$STATUS" -eq 0 ]; then log "ALL JOURNEYS PASSED"; else log "JOURNEYS FAILED (exit $STATUS)"; fi
exit "$STATUS"
