#!/usr/bin/env bash
# Steps 09 and 10 checks: regression of Steps 01-08 gates, the console, page content and publication on the Compose
# stack in live mode with the real .env: the new collections, every console screen rendering for a real project, the
# public page serving nothing unpublished, content and publication APIs matching their contracts, prompt caching
# configured, the browser journeys (separate journey database), and hygiene. It proves it spent nothing: the model
# call ledger and provider quotas are the same before and after.
# Output is printed and saved to logs/step-09/checks-<UTC time>.log (Step 10 shares it). Secret values are read from
# .env but never printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step09_10_checks.sh
#
# Needs Docker, uv, pnpm, Node.js, Python 3.10+ and Playwright's Chromium (pnpm exec playwright install chromium);
# `gh` signed in. No run is started and no model is called.

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-09
mkdir -p "$LOG_DIR" logs/step-10
LOG="$LOG_DIR/checks-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILED=0
PY="$ROOT/.venv/bin/python"
UV="env -u VIRTUAL_ENV uv"
WEB=http://127.0.0.1:3000
JAR="$T/cookies.txt"

expect() { # expect <name> <expected exit code> <command...>
  local name=$1 want=$2
  shift 2
  printf '\n=== %s ===\n$ %s\n' "$name" "$*"
  "$@"
  local got=$?
  if [ "$got" -eq "$want" ]; then
    echo "--> OK (exit $got, expected $want)"
  else
    echo "--> NOT OK (exit $got, expected $want)"
    FAILED=1
  fi
}

env_value() { sed -n "s/^$1=//p" .env | tail -1; }

contract_ok() { # contract_ok <ref>: the last response body matches this contract definition
  "$PY" - "$T/body" "$1" <<'EOF'
import json, sys
sys.path.insert(0, "scripts")
import contract_tools as ct
body = json.load(open(sys.argv[1]))
errors = ct.Contracts().errors(body, sys.argv[2])
print(f"{sys.argv[2].rsplit('/', 1)[-1]}: {'matches the contract' if not errors else errors[:3]}")
sys.exit(1 if errors else 0)
EOF
}

csrf() { awk -F'\t' '$6 == "sy_csrf" {print $7}' "$JAR"; }

api_json() { # api_json <METHOD> <path>: signed-in call through the web app
  curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X "$1" -H "X-Check: step09-10" "$WEB$2"
}

first_project() { # id and slug of the first real project (by slug)
  docker compose exec -T api python -c "from app.db import get_db; p = get_db().projects.find_one({}, sort=[('slug', 1)]); print(p['_id'], p['slug'])"
}

spend_snapshot() { # model calls and spent USD, then provider quota use (for the before/after comparison)
  docker compose exec -T api python - <<'EOF'
from app.db import get_db
db = get_db()
calls = db.ai_model_calls.count_documents({})
spent = sum(b.get("spent_usd", 0) for b in db.ai_model_budget.find())
quota = sorted((q["_id"], q.get("used", 0)) for q in db.ai_connector_quota.find())
print(f"{calls} {spent:.6f} {quota}")
EOF
}

# ---------- Stack ----------

services_running() {
  local running missing=0 name
  running=$(docker compose ps --status running --services)
  for name in mongodb api worker media-worker embedder scheduler web; do
    if echo "$running" | grep -qx "$name"; then echo "$name running"; else echo "$name NOT running"; missing=1; fi
  done
  return $missing
}

mongodb_healthy() {
  local status i
  for i in $(seq 1 60); do
    status=$(docker inspect agentic_ai_review_model-mongodb-1 --format '{{.State.Health.Status}}' 2>/dev/null)
    if [ "$status" = healthy ]; then echo "mongodb healthy after $((i * 5 - 5)) s"; return 0; fi
    sleep 5
  done
  echo "mongodb still $status after 5 minutes"
  return 1
}

live_with_real_credentials() {
  local mode
  mode=$(curl -s http://127.0.0.1:8000/healthz | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["mode"])')
  echo "API mode: $mode (expected live)"
  docker compose exec -T api python -m app.cli check-config > "$T/config.json" || return 1
  "$PY" - "$T/config.json" "$mode" <<'EOF'
import json, sys
c = json.load(open(sys.argv[1]))
present = sorted(k for k, v in c.get("credentials_present", {}).items() if v)
print(f"credentials present in the API container (names only): {present}")
ok = sys.argv[2] == "live" and "ANTHROPIC_API_KEY" in present and "BRAVE_SEARCH_API_KEY" in present
sys.exit(0 if ok else 1)
EOF
}

setup_has_new_collections() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup1.json" || return 1
  docker compose exec -T api python -m app.cli setup-db > "$T/setup2.json" || return 1
  "$PY" - "$T/setup1.json" "$T/setup2.json" <<'EOF'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
wanted = ["ai_corrections", "ai_content_qa", "ai_publication_state", "ai_publication_operations", "ai_content_revisions"]
present = [n for n in wanted if n in second["collections"]]
changed = {n: e for n, e in second["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"Step 09-10 collections present: {present}; changed on repeat: {changed or 'none'}")
sys.exit(0 if len(present) == len(wanted) and not changed else 1)
EOF
}

sign_in() {
  rm -f "$JAR"
  local code
  code=$(EMAIL=deepesh.gupta@client-site.example PASSWORD="$SEED_PASSWORD" "$PY" -c \
    'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))' \
    | curl -s -o "$T/body" -w '%{http_code}' -c "$JAR" -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login")
  echo "HTTP $code (expected 200)"
  [ "$code" = 200 ]
}

console_screens_render() {
  read -r pid slug < <(first_project)
  local path code bad=0
  for path in /console /console/corrections /console/operations /console/admin \
    "/console/projects/$pid/setup" "/console/projects/$pid/runs" "/console/projects/$pid/evidence" \
    "/console/projects/$pid/videos" "/console/projects/$pid/findings" "/console/projects/$pid/reviews" \
    "/console/projects/$pid/content" "/console/projects/$pid/publishing"; do
    code=$(curl -s -o "$T/page.html" -w '%{http_code}' -b "$JAR" "$WEB$path")
    if [ "$code" = 200 ] && ! grep -q "Fixture mode" "$T/page.html"; then echo "  $code $path"; else echo "  $code $path NOT OK"; bad=1; fi
  done
  code=$(curl -s -o "$T/page.html" -w '%{http_code}' "$WEB/console")
  echo "  signed out, /console answers $code (a redirect to sign in)"
  [ "$code" = 307 ] || [ "$code" = 302 ] || bad=1
  return $bad
}

portfolio_and_content_contracts() {
  read -r pid slug < <(first_project)
  local code
  code=$(api_json GET "/v1/projects?limit=100"); echo "listProjects HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/ProjectPage" || return 1
  code=$(api_json GET "/v1/projects/$pid/content-revisions"); echo "listContentRevisions HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/ContentRevisionPage" || return 1
  code=$(api_json GET "/v1/projects/$pid/publication"); echo "getPublicationState HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/PublicationStateView" || return 1
  code=$(api_json GET "/v1/corrections"); echo "listCorrections HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/CorrectionPage" || return 1
  code=$(api_json GET "/v1/admin/users"); echo "listUsers HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/UserPage"
}

public_page_serves_only_active() {
  read -r pid slug < <(first_project)
  local code state
  code=$(curl -s -o "$T/body" -w '%{http_code}' "$WEB/v1/public/projects/$slug/insights")
  state=$(docker compose exec -T api python -c "from app.db import get_db; s = get_db().ai_publication_state.find_one({'project_id': '$pid'}); print((s or {}).get('serving_state', 'unpublished'))")
  echo "public insights for $slug: HTTP $code; serving state $state"
  curl -s "$WEB/projects/$slug" -o "$T/page.html"
  grep -o 'data-insights-state="[a-z]*"' "$T/page.html" | head -1
  if [ "$state" = active ]; then [ "$code" = 200 ]; else [ "$code" = 404 ] && grep -q 'data-insights-state="empty"' "$T/page.html"; fi
}

prompt_caching_configured() {
  docker compose exec -T api python - <<'EOF'
from app.agents.gateway import cached_system
from app.config import REPO_ROOT, get_settings
s = get_settings()
print(f"  prompt cache {s.model_prompt_cache}; live {s.model_cache_ttl}, batches {s.model_batch_cache_ttl}; minimums {s.model_cache_min_tokens}")
ok = s.model_prompt_cache
for agent, role in (("a05_claim_extractor.1.0", "light"), ("a11_review_curator.1.0", "light"), ("a07_findings_synthesiser.1.2", "routine"), ("a08_seo_aeo_editor.1.0", "routine"), ("a09_editorial_qa.1.0", "routine")):
    text = (REPO_ROOT / "prompts" / f"{agent}.md").read_text("utf-8")
    model = s.model_for_role(role)
    sent, cached = cached_system(s, model, text, s.model_cache_ttl)
    print(f"  {agent:30} {model:18} {'breakpoint on the instructions' if cached else 'sent plain (below the minimum)'}")
    ok = ok and (role != "light" or cached > 0)
raise SystemExit(0 if ok else 1)
EOF
}

browser_journeys() {
  bash scripts/run_step09_e2e.sh > "$T/e2e.out" 2>&1
  local code=$?
  grep -E "✓|✘|passed|failed|JOURNEYS|API mode|seed:" "$T/e2e.out" | sed 's/^/  /' | tail -20
  return $code
}

no_spend_during_checks() {
  local after
  after=$(spend_snapshot)
  echo "before: $SPEND_BEFORE"
  echo "after:  $after"
  [ "$after" = "$SPEND_BEFORE" ]
}

# ---------- Hygiene ----------

no_tracked_secrets_or_env() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$|(^|/)\.venv/|(^|/)node_modules/|(^|/)\.next/|test-results/|playwright-report/|^exports/')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env, .venv, node_modules, .next, Playwright output or exports tracked"
}

secrets_not_in_repo_or_logs() {
  docker compose logs --no-color > "$T/compose.log" 2>&1
  local name value hit found=0
  for name in SEED_USER_PASSWORD SESSION_SECRET REVALIDATION_SECRET ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY YOUTUBE_API_KEY SCRAPFLY_API_KEY FIRECRAWL_API_KEY; do
    value=$(env_value "$name")
    if [ -z "$value" ]; then echo "$name: not set, nothing to look for"; continue; fi
    hit=0
    if git grep -qF -- "$value" HEAD -- . 2>/dev/null; then echo "$name: FOUND in committed files"; hit=1; fi
    if grep -qF -- "$value" "$T/compose.log"; then echo "$name: FOUND in service logs"; hit=1; fi
    if grep -rqF -- "$value" logs/ web/test-results 2>/dev/null; then echo "$name: FOUND in logs/"; hit=1; fi
    [ "$hit" -eq 0 ] && echo "$name: not in committed files, service logs or logs/"
    [ "$hit" -eq 1 ] && found=1
  done
  return $found
}

ci_not_failing() {
  local line
  line=$(gh run list --branch main --limit 1 --json headSha,status,conclusion,displayTitle \
    -q '.[0] | "\(.headSha[0:7]) \(.status) \(.conclusion) \(.displayTitle)"') || return 2
  echo "latest CI run on main: $line"
  echo "$line" | grep -qE ' (completed success|in_progress |queued )'
}

# ---------- Run ----------

if [ ! -x "$PY" ]; then python3 -m venv .venv >/dev/null; fi
"$PY" -m pip install -q -r scripts/requirements.txt >/dev/null 2>&1
(cd web && pnpm install --frozen-lockfile --silent) >/dev/null 2>&1
(cd backend && $UV sync --frozen --quiet) >/dev/null 2>&1
SEED_PASSWORD=$(env_value SEED_USER_PASSWORD)

exec 3>&1 >"$LOG" 2>&1

echo "Steps 09 and 10 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Contracts: checker, fixtures and the JavaScript hash cross-check (api 1.5.0, content 1.2.0, common 1.3.0, evidence 1.1.0, routes 1.4.0)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-81: backend tests against the Compose replica set (no real credentials, no model call)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests (role map equals the contract)" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Images build" 0 docker compose build
expect "MongoDB is healthy again after the builds" 0 mongodb_healthy
expect "Stack starts and every service is healthy" 0 docker compose up -d --wait
expect "Long-running services up" 0 services_running
SPEND_BEFORE=$(spend_snapshot)
echo "model calls, spent USD and provider quota use now: $SPEND_BEFORE"
expect "D64: the stack runs in live mode and the API holds the real credentials (names only)" 0 live_with_real_credentials
expect "Database setup has the Step 09-10 collections; a repeat changes nothing" 0 setup_has_new_collections
expect "Sign in through the web app" 0 sign_in
expect "Step 09: every console screen renders for a real project, without the fixture banner; signed out redirects" 0 console_screens_render
expect "Step 09-10: portfolio, content, publication, corrections and users through the API match their contracts" 0 portfolio_and_content_contracts
expect "Step 10: the public page serves only an active revision (empty state otherwise, never a draft)" 0 public_page_serves_only_active
expect "D65: prompt caching marks the instructions of the cacheable agents" 0 prompt_caching_configured
expect "Step 09.7: browser journeys (journey database, real environment, no run started)" 0 browser_journeys
expect "These checks spent nothing: model calls and provider quotas unchanged" 0 no_spend_during_checks

expect "Hygiene: nothing generated, secret or downloaded is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
