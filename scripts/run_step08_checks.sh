#!/usr/bin/env bash
# Step 08 checks: Steps 01-07 regression, backend and web gates, and the agents and analysis workflow on the Compose
# stack: the Step 08 collections, the new source policies (instagram_public v1, meta v2) and connector, the model roles
# and spend ledger (D53), the dry-run analysis plan, the analysis of the five real projects (stage, report and the
# read-only analysis rules), findings and reviews through the API (contract shape, exact-revision decisions), the
# saved agent evaluation, and hygiene.
# Output is printed and saved to logs/step-08/checks-<UTC time>.log. Secret values are read from .env but never
# printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step08_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in. This script makes no Claude call: the real
# analysis and the agent evaluation are run once by hand (logs/step-08/README.md) and checked here.

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-08
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checks-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILED=0
PY="$ROOT/.venv/bin/python"
UV="env -u VIRTUAL_ENV uv"
WEB=http://127.0.0.1:3000
JAR="$T/cookies.txt"
STAMP=$(date -u +%s)

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

env_value() { # env_value <NAME>: one value from .env, for use in a variable; never printed
  sed -n "s/^$1=//p" .env | tail -1
}

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

error_code_is() { # error_code_is <code>: the last response is the error envelope with this code
  "$PY" -c 'import json, sys; e = json.load(open(sys.argv[1]))["error"]; print("error:", e["code"], "-", e["message"]); sys.exit(0 if e["code"] == sys.argv[2] else 1)' "$T/body" "$1"
}

csrf() { awk -F'\t' '$6 == "sy_csrf" {print $7}' "$JAR"; }

api_json() { # api_json <METHOD> <path> [json body] [extra header]: signed-in call through the web app
  local method=$1 path=$2 body=${3:-} header=${4:-X-Check: step08}
  if [ -n "$body" ]; then
    curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X "$method" -H 'Content-Type: application/json' \
      -H "X-CSRF-Token: $(csrf)" -H "$header" --data-binary "$body" "$WEB$path"
  else
    curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X "$method" -H "$header" "$WEB$path"
  fi
}

project_id() { # project_id <slug>
  docker compose exec -T api python -c "from app.db import get_db; print(get_db().projects.find_one({'slug': '$1'})['_id'])"
}

latest_run() { # latest_run <project id>
  docker compose exec -T api python -c "from app.db import get_db; print(get_db().ai_runs.find_one({'project_id': '$1'}, sort=[('_id', -1)])['_id'])"
}

# ---------- Stack and data ----------

services_running() {
  local running missing=0 name
  running=$(docker compose ps --status running --services)
  for name in mongodb api worker media-worker embedder scheduler web; do
    if echo "$running" | grep -qx "$name"; then echo "$name running"; else echo "$name NOT running"; missing=1; fi
  done
  return $missing
}

mongodb_healthy() { # builds load the VM; wait until MongoDB's own health probe passes again (at most 5 minutes)
  local status i
  for i in $(seq 1 60); do
    status=$(docker inspect agentic_ai_review_model-mongodb-1 --format '{{.State.Health.Status}}' 2>/dev/null)
    if [ "$status" = healthy ]; then echo "mongodb healthy after $((i * 5 - 5)) s"; return 0; fi
    sleep 5
  done
  echo "mongodb still $status after 5 minutes"
  return 1
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

setup_has_step08_collections() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup1.json" || return 1
  docker compose exec -T api python -m app.cli setup-db > "$T/setup2.json" || return 1
  "$PY" - "$T/setup1.json" "$T/setup2.json" <<'EOF'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
wanted = ["ai_model_budget", "ai_model_batches", "ai_model_calls", "ai_agent_outputs", "ai_findings", "ai_review_excerpts"]
present = [n for n in wanted if n in second["collections"]]
made = {n: e["indexes_created"] for n, e in first["collections"].items() if e["created"] or e["indexes_created"] or e["validator"] != "unchanged"}
changed = {n: e for n, e in second["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"first pass changed: {made or 'nothing (already set up)'}")
print(f"Step 08 collections present: {present}; changed on repeat: {changed or 'none'}")
sys.exit(0 if len(present) == len(wanted) and not changed else 1)
EOF
}

policies_and_connector_seeded() {
  docker compose exec -T api python -m app.cli seed-policies > "$T/policies.json" || return 1
  docker compose exec -T api python -m app.cli seed-projects > "$T/projects.json" || return 1
  docker compose exec -T api python - <<'EOF'
from app.db import get_db
from app.sources import policies
db = get_db()
ig, meta = policies.current(db, "instagram_public"), policies.current(db, "meta")
print(f"  instagram_public v{ig and ig['policy_version']}: collect {ig and ig['collection_allowed']}, quote {ig and ig['quotation_allowed']}, robots {ig and ig['robots_txt']}, retention {ig and ig['retention_days']} days, hosts {ig and ig['hosts']}")
print(f"  meta v{meta and meta['policy_version']}: collect {meta and meta['collection_allowed']}, hosts {meta and meta['hosts']}")
resolved = policies.resolve(db, "https://www.instagram.com/p/Cq1AbCdEfGh/")
print(f"  instagram.com resolves to {resolved.family} ({resolved.reason})")
configs = list(db.ai_project_configs.find({}, {"sources": 1}))
with_ig = sum(any(s["connector_id"] == "instagram_public" for s in c["sources"]) for c in configs)
print(f"  project configurations listing instagram_public: {with_ig}/{len(configs)}")
ok = ig and ig["policy_version"] == 1 and meta and meta["hosts"] == ["facebook.com"] and resolved.family == "instagram_public" and with_ig == len(configs) == 5
raise SystemExit(0 if ok else 1)
EOF
}

models_and_budget() {
  docker compose exec -T api python - <<'EOF'
from app.agents.spend import SpendLedger
from app.config import get_settings
from app.db import get_db
s = get_settings()
roles = {r: s.model_for_role(r) for r in ("light", "routine", "reasoning", "difficult")}
print(f"  model roles: {roles}")
print(f"  prices known for: {sorted(s.model_prices)}")
db = get_db()
budget = db.ai_model_budget.find_one({"_id": SpendLedger(db, s).budget_id})
spent = budget["spent_usd"] if budget else 0.0
print(f"  budget {s.model_budget_usd:.2f} USD since {s.model_budget_since.date()}; spent {spent:.4f}; calls {budget['calls'] if budget else 0}")
missing = [m for m in set(roles.values()) if m not in s.model_prices]
raise SystemExit(0 if not missing and spent <= s.model_budget_usd and s.model_budget_usd <= 2.0 else 1)
EOF
}

plan_is_within_budget() {
  docker compose exec -T api python -m app.cli plan-analysis > "$T/plan.json" || return 1
  "$PY" - "$T/plan.json" <<'EOF'
import json, sys
p = json.load(open(sys.argv[1]))
for row in p["projects"]:
    print(f"  {row['project'][:24]:24} A05 {row['a05']['tasks']:>3} tasks ({row['a05']['cached']} cached) worst {row['a05']['worst_usd']:.4f}; A11 {row['a11']['tasks']:>2} tasks ({row['a11']['cached']} cached) worst {row['a11']['worst_usd']:.4f}")
print(f"  worst case for A05 and A11 now: {p['worst_case_usd_a05_a11']} USD of a {p['budget_usd']} USD budget")
sys.exit(0 if p["worst_case_usd_a05_a11"] <= p["budget_usd"] else 1)
EOF
}

real_analysis_reached_review() {
  docker compose exec -T api python - <<'EOF'
from app.db import get_db
from app.workflows.analysis import spent_usd
db = get_db()
ok = True
for p in db.projects.find({}, {"project_name": 1}).sort("slug", 1):
    run = db.ai_runs.find_one({"project_id": p["_id"], "stage": {"$in": ["findings_review", "insufficient_evidence", "formatting"]}}, sort=[("_id", -1)])
    if run is None:
        latest = db.ai_runs.find_one({"project_id": p["_id"]}, sort=[("_id", -1)])
        print(f"  {p['project_name'][:24]:24} no analysed run (latest {latest and latest['_id']} {latest and latest['stage']}: {latest and latest['outcome_note']})")
        ok = False
        continue
    job = db.ai_jobs.find_one({"run_id": run["_id"], "kind": "analyse"}, sort=[("created_at", -1)])
    counts = {c: db[f"ai_{c}"].count_documents({"project_id": p["_id"]}) for c in ("claims", "findings", "review_excerpts")}
    print(f"  {p['project_name'][:24]:24} {run['_id']} {run['stage']:21} job {job and job['status']}; spent {spent_usd(db, run['_id']):.4f} USD; stored {counts}")
    print(f"  {'':24} {run['outcome_note']}")
    ok = ok and job is not None and job["status"] in ("waiting_review", "completed")
raise SystemExit(0 if ok else 1)
EOF
}

analysis_rules_hold() {
  docker compose exec -T api python -m app.cli verify-analysis > "$T/verify-analysis.json"
  local code=$?
  "$PY" - "$T/verify-analysis.json" <<'EOF'
import json, sys
for r in json.load(open(sys.argv[1])):
    print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['check']:86} looked at {r['looked_at']:<5} broken {r['broken']}")
EOF
  return $code
}

findings_through_the_api() {
  local pid code
  pid=$(docker compose exec -T api python -c "from app.db import get_db; d = get_db(); f = d.ai_findings.find_one({}, sort=[('_id', 1)]); print(f['project_id'] if f else d.projects.find_one()['_id'])")
  code=$(api_json GET "/v1/projects/$pid/findings?limit=5")
  echo "findings HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/FindingPage" || return 1
  "$PY" -c 'import json, sys; items = json.load(open(sys.argv[1]))["items"]; [print(f"  {i[\"finding\"][\"kind\"]:7} {i[\"finding\"][\"aspect\"]:22} {i[\"finding\"][\"attribution\"]:16} r{i[\"finding\"][\"revision\"]} {i[\"finding\"][\"review_status\"]:9} eligible {i[\"eligible\"]}  {i[\"finding\"][\"wording\"][:70]!r}") for i in items]' "$T/body"
  code=$(api_json GET "/v1/projects/$pid/review-excerpts?limit=5")
  echo "reviews HTTP $code"
  [ "$code" = 200 ] && contract_ok "api.schema.json#/\$defs/ReviewExcerptPage"
}

stale_decision_refused() {
  local fid code
  fid=$(docker compose exec -T api python -c "from app.db import get_db; f = get_db().ai_findings.find_one({}, sort=[('_id', 1)]); print(f['id'] if f else '')")
  if [ -z "$fid" ]; then echo "no finding stored"; return 1; fi
  code=$(api_json POST "/v1/findings/$fid/decisions" '{"revision": 999, "action": "approve", "reason": null}')
  echo "decision on revision 999 of $fid: HTTP $code (expected 409; nothing changes)"
  [ "$code" = 409 ] && error_code_is version_conflict || return 1
  code=$(api_json POST "/v1/findings/fnd_00000000000000000000000000/decisions" '{"revision": 1, "action": "approve", "reason": null}')
  echo "decision on an unknown finding: HTTP $code (expected 404)"
  [ "$code" = 404 ]
}

agent_evaluation_saved() {
  docker compose exec -T api python - <<'EOF'
from app.db import get_db
rows = list(get_db().ai_evaluations.find({"dataset.name": "agents-synthetic"}).sort("created_at", 1))
for r in rows:
    m = {x["name"]: x["value"] for x in r["metrics"]}
    print(f"  {r['_id']} {r['config']['model']}: recall {m.get('a05_claim_recall')}, forbidden {m.get('a05_forbidden_claims')}, reviews {m.get('a11_review_accuracy')}, verification passed {m.get('a06_verification_checks_passed')}, cost {m.get('cost_usd')} USD")
raise SystemExit(0 if rows else 1)
EOF
}

evidence_rules_hold() {
  docker compose exec -T api python -m app.cli verify-evidence > "$T/verify-evidence.json"
  local code=$?
  "$PY" - "$T/verify-evidence.json" <<'EOF'
import json, sys
for r in json.load(open(sys.argv[1])):
    print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['check']:72} looked at {r['looked_at']:<5} broken {r['broken']}")
EOF
  return $code
}

collection_rules_hold() {
  docker compose exec -T api python -m app.cli verify-collection > "$T/verify.json"
  local code=$?
  "$PY" - "$T/verify.json" <<'EOF'
import json, sys
rows = json.load(open(sys.argv[1]))
print(f"  {sum(r['ok'] for r in rows)}/{len(rows)} collection rules hold")
for r in rows:
    if not r["ok"]:
        print(f"  FAIL {r['check']} broken {r['broken']}")
EOF
  return $code
}

# ---------- Hygiene ----------

no_tracked_secrets_or_env() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$|(^|/)\.venv/|(^|/)node_modules/|(^|/)\.next/|\.wav$|\.mp4$|\.m4a$|\.webm$')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env, .venv, node_modules, .next or downloaded media tracked (the synthetic .opus clips are the only audio)"
}

secrets_not_in_repo_or_logs() {
  docker compose logs --no-color > "$T/compose.log" 2>&1
  local name value hit found=0
  for name in SEED_USER_PASSWORD SESSION_SECRET REVALIDATION_SECRET ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY YOUTUBE_API_KEY SCRAPFLY_API_KEY; do
    value=$(env_value "$name")
    if [ -z "$value" ]; then echo "$name: not set, nothing to look for"; continue; fi
    hit=0
    if git grep -qF -- "$value" HEAD -- . 2>/dev/null; then echo "$name: FOUND in committed files"; hit=1; fi
    if grep -qF -- "$value" "$T/compose.log"; then echo "$name: FOUND in service logs"; hit=1; fi
    if grep -rqF -- "$value" logs/; then echo "$name: FOUND in logs/"; hit=1; fi
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

if [ ! -x "$PY" ]; then
  python3 -m venv .venv >/dev/null
fi
"$PY" -m pip install -q -r scripts/requirements.txt >/dev/null 2>&1
python3 scripts/init_env.py >/dev/null
(cd web && pnpm install --frozen-lockfile --silent) >/dev/null 2>&1
(cd backend && $UV sync --frozen --quiet) >/dev/null 2>&1
SEED_PASSWORD=$(env_value SEED_USER_PASSWORD)

exec 3>&1 >"$LOG" 2>&1

echo "Step 08 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) | Docker VM memory $(docker info --format '{{.MemTotal}}' 2>/dev/null) bytes"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: contract checker" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-65: backend tests against the Compose replica set (no real credentials, no model call)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Images build" 0 docker compose build
expect "MongoDB is healthy again after the builds" 0 mongodb_healthy
expect "Stack starts and every service is healthy" 0 docker compose up -d --wait
expect "Long-running services up" 0 services_running
expect "Database setup has the Step 08 collections; a repeat changes nothing" 0 setup_has_step08_collections
expect "D54: instagram_public v1 governs instagram.com, meta v2 is Facebook only; every project lists the connector" 0 policies_and_connector_seeded
expect "D53: model roles priced, budget at most 2 USD and not overspent" 0 models_and_budget
expect "D53: the dry-run plan of the next analysis fits the budget (no model call)" 0 plan_is_within_budget
expect "UC-59: the real analysis of each project reached findings review (or an honest insufficient evidence)" 0 real_analysis_reached_review
expect "UC-55..58: the analysis rules hold on the real stored claims, findings, reviews, approvals and spend" 0 analysis_rules_hold
expect "Sign in through the web app" 0 sign_in
expect "UC-60: findings and reviews through the API match their contracts" 0 findings_through_the_api
expect "UC-60: a decision on a stale revision or an unknown finding is refused" 0 stale_decision_refused
expect "UC-65: the agent evaluation on the labelled synthetic set is saved" 0 agent_evaluation_saved
expect "Regression: the collection rules still hold (verify-collection)" 0 collection_rules_hold
expect "Regression: the evidence rules still hold (verify-evidence)" 0 evidence_rules_hold

expect "Hygiene: nothing generated, secret or downloaded is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
