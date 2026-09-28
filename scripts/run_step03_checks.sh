#!/usr/bin/env bash
# Step 03 checks: Step 01-02 regression, backend and web quality gates, the Docker Compose
# stack end to end (replica set, repeatable setup and seeding, sign-in through the web app,
# jobs across a real worker restart, the model smoke test), negative checks and hygiene.
# Output is printed and saved to logs/step-03/checks-<UTC time>.log. Secret values are read
# from .env but never printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step03_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in for the GitHub checks.
# It starts the stack if needed and leaves it running (stop it with `make down`).

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-03
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checks-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILED=0
PY="$ROOT/.venv/bin/python"
UV="env -u VIRTUAL_ENV uv"
WEB=http://127.0.0.1:3000
API=http://127.0.0.1:8000
JAR="$T/cookies.txt"
CHECK_KEY="step03-check-$(date -u +%s)"

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

expect_failure() { # expect_failure <name> <text the output must contain> <command...>
  local name=$1 needle=$2
  shift 2
  printf '\n=== %s ===\n$ %s\n' "$name" "$*"
  local out got
  out=$("$@" 2>&1)
  got=$?
  echo "$out" | grep -F -- "$needle" | head -3 || true
  if [ "$got" -ne 0 ] && echo "$out" | grep -qF -- "$needle"; then
    echo "--> OK (failed as expected, exit $got)"
  else
    echo "--> NOT OK (exit $got; expected a failure mentioning: $needle)"
    FAILED=1
  fi
}

env_value() { # env_value <NAME>: one value from .env, for use in a variable; never printed
  sed -n "s/^$1=//p" .env | tail -1
}

in_api() { # in_api <python code>: run Python inside the api container (app settings and DB)
  docker compose exec -T api python -c "$1"
}

status_is() { # status_is <expected HTTP status> <curl arguments...>
  local want=$1 got
  shift
  got=$(curl -s -o "$T/body" -w '%{http_code}' "$@")
  echo "HTTP $got (expected $want)"
  [ "$got" = "$want" ]
}

body_has() { # body_has <text...>: the last response body contains every text
  local text
  for text in "$@"; do
    if grep -qF -- "$text" "$T/body"; then echo "found: $text"; else echo "missing: $text"; return 1; fi
  done
}

login_body() { # login_body <email> <password env var name>: JSON body on stdout, password never echoed
  EMAIL=$1 PASSWORD="${!2}" "$PY" -c 'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))'
}

# ---------- Stack checks ----------

services_running() {
  local running missing=0 name
  running=$(docker compose ps --status running --services)
  for name in mongodb api worker scheduler web; do
    if echo "$running" | grep -qx "$name"; then echo "$name running"; else echo "$name NOT running"; missing=1; fi
  done
  docker compose ps -a --format '{{.Service}}: {{.State}} {{.Status}}' | grep -E '^(mongo-init|db-setup):'
  return $missing
}

replica_set_primary() {
  local out
  out=$(docker compose exec -T mongodb mongosh --quiet --eval 'print(rs.status().set + " primary=" + db.hello().isWritablePrimary)')
  echo "$out"
  [ "$out" = "rs0 primary=true" ]
}

api_ready() {
  curl -fsS "$API/readyz" && echo
}

setup_db_is_a_no_op() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup.json" || return 1
  "$PY" - "$T/setup.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
changed = {name: entry for name, entry in report["collections"].items()
           if entry["created"] or entry["validator"] != "unchanged" or entry["indexes_created"]}
print(f"{len(report['collections'])} collections checked; changed on repeat: {changed or 'none'}")
sys.exit(1 if changed else 0)
EOF
}

no_duplicate_indexes() {
  in_api '
from app.db import get_db
db = get_db()
bad = []
for name in sorted(db.list_collection_names()):
    keys = [tuple(ix["key"].items()) for ix in db[name].list_indexes()]
    if len(keys) != len(set(keys)):
        bad.append(name)
    print(f"{name}: {len(keys)} indexes")
raise SystemExit(1 if bad else 0)
'
}

seed_projects_twice() {
  docker compose exec -T api python -m app.cli seed-projects > /dev/null || return 1
  docker compose exec -T api python -m app.cli seed-projects > "$T/seed.json" || return 1
  "$PY" - "$T/seed.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
for item in report:
    print(f"{item['slug']}: {item['outcome']}")
sys.exit(0 if len(report) == 5 and all(item["outcome"] == "unchanged" for item in report) else 1)
EOF
}

five_projects_stored() {
  in_api '
from app.db import get_db
db = get_db()
slugs = sorted(p["slug"] for p in db.projects.find({}, {"slug": 1}))
print(len(slugs), "projects:", ", ".join(slugs))
raise SystemExit(0 if len(slugs) == 5 and len(set(slugs)) == 5 else 1)
'
}

seed_users_repeat() {
  docker compose exec -T api python -m app.cli seed-users > "$T/users.json" || return 1
  "$PY" - "$T/users.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
for item in report:
    print(f"{item['email']}: {item['outcome']}; roles {', '.join(item['roles'])}")
sys.exit(0 if report and all(item["outcome"] == "unchanged" for item in report) else 1)
EOF
}

smoke_model() {
  local out
  out=$(docker compose exec -T api python -m app.cli smoke-model) || { echo "$out"; return 1; }
  echo "$out"
  if [ -n "$(env_value ANTHROPIC_API_KEY)" ]; then
    echo "$out" | grep -q '"outcome": "completed"'
  else
    echo "$out" | grep -q '^skipped: no ANTHROPIC_API_KEY configured'
  fi
}

config_shows_names_only() {
  docker compose exec -T api python -m app.cli check-config > "$T/config.json" || return 1
  "$PY" - "$T/config.json" <<'EOF'
import json, sys
config = json.load(open(sys.argv[1]))
print("mode:", config["mode"], "| models:", config["models"])
present = config["credentials_present"]
print("credentials present:", sorted(k for k, v in present.items() if v) or "none", "| absent:", len([v for v in present.values() if not v]))
sys.exit(0 if all(isinstance(v, bool) for v in present.values()) else 1)
EOF
}

# ---------- Sign-in through the web app (same origin as the browser) ----------

signed_out_console_redirects() {
  status_is 307 "$WEB/console" || return 1
  grep -i '^location:' <(curl -sI "$WEB/console")
  curl -sI "$WEB/console" | grep -qi '^location: /console/login?next=%2Fconsole'
}

signed_out_api_is_401() {
  status_is 401 "$WEB/v1/auth/me" && body_has '"code":"unauthenticated"'
}

wrong_password_is_401() {
  local WRONG="not-the-password-$RANDOM$RANDOM"
  login_body "$COORDINATOR" WRONG | status_is 401 -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login"
}

login_sets_cookies() {
  rm -f "$JAR"
  login_body "$COORDINATOR" SEED_PASSWORD | status_is 200 -c "$JAR" -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login" || return 1
  grep -E '#HttpOnly_[^	]*	.*	sy_session	' "$JAR" > /dev/null && echo "sy_session is HttpOnly" || { echo "sy_session missing or not HttpOnly"; return 1; }
  grep -E '	sy_csrf	' "$JAR" > /dev/null && echo "sy_csrf present (readable by the page)" || { echo "sy_csrf missing"; return 1; }
}

me_has_all_roles() {
  status_is 200 -b "$JAR" "$WEB/v1/auth/me" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
me = json.load(open(sys.argv[1]))
roles = sorted(me["user"]["roles"] if "user" in me else me["roles"])
print("roles:", ", ".join(roles))
sys.exit(0 if len(roles) == 5 else 1)
EOF
}

console_shows_user_and_projects() {
  status_is 200 -b "$JAR" "$WEB/v1/ops/summary" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
projects = json.load(open(sys.argv[1]))["projects"]
print("operations summary:", len(projects), "projects")
sys.exit(0 if len(projects) == 5 else 1)
EOF
  status_is 200 -b "$JAR" "$WEB/console" || return 1
  body_has "Deepesh Gupta" "Fixture mode: sample data only" '<span class="font-semibold">5</span> projects in the catalogue'
}

operations_lists_connectors() {
  status_is 200 -b "$JAR" "$WEB/v1/connectors/health" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
connectors = json.load(open(sys.argv[1]))["connectors"]
statuses = {c["status"] for c in connectors}
print(len(connectors), "connectors; statuses:", ", ".join(sorted(statuses)))
sys.exit(0 if len(connectors) == 11 and statuses == {"access_pending"} else 1)
EOF
  status_is 200 -b "$JAR" "$WEB/console/operations" || return 1
  local rows
  rows=$(grep -o 'data-testid="connector-row"' "$T/body" | wc -l | tr -d ' ')
  echo "operations page rows: $rows"
  [ "$rows" = "11" ]
}

public_page_empty_and_noindex() {
  status_is 200 "$WEB/projects/dlf-privana-sector-76-gurgaon" || return 1
  body_has 'data-insights-state="empty"' 'noindex'
}

logout_needs_csrf() {
  status_is 403 -b "$JAR" -X POST "$WEB/v1/auth/logout" || return 1
  body_has 'Missing or invalid CSRF token' || return 1
  local csrf
  csrf=$(awk -F'\t' '$6 == "sy_csrf" {print $7}' "$JAR")
  status_is 204 -b "$JAR" -X POST -H "X-CSRF-Token: $csrf" "$WEB/v1/auth/logout" || return 1
  echo "old session cookie after logout:"
  status_is 401 -b "$JAR" "$WEB/v1/auth/me"
}

login_rate_limited() {
  local i code WRONG="not-the-password-$RANDOM$RANDOM" email="rate-limit-check-$RANDOM@example.invalid"
  for i in $(seq 1 12); do
    code=$(login_body "$email" WRONG | curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login")
    printf '%s ' "$code"
  done
  echo
  [ "$code" = "429" ]
}

# ---------- Jobs on the real worker ----------

job_survives_worker_restart() {
  docker compose stop -t 30 worker > /dev/null 2>&1 || return 1
  echo "worker stopped"
  in_api "
import json
from app.db import get_db
from app.jobs import queue
db = get_db()
job, created = queue.enqueue(db, 'collect', '$CHECK_KEY', max_attempts=3)
claimed = queue.claim(db, 'worker-before-restart', 2)
assert claimed is not None and claimed.id == job['_id'], 'the check job was not the one claimed'
json.dump({'job_id': claimed.id, 'token': claimed.token}, open('/tmp/step03_job.json', 'w'))
print('claimed', claimed.id, 'as worker-before-restart with fencing token', claimed.token, 'and a 2 s lease')
" || { docker compose start worker > /dev/null; return 1; }
  sleep 3
  docker compose start worker > /dev/null 2>&1 || return 1
  echo "worker started again"
  in_api "
import json, time
from app.db import get_db
from app.jobs import queue
db = get_db()
old = json.load(open('/tmp/step03_job.json'))
for _ in range(60):
    job = db.ai_jobs.find_one({'_id': old['job_id']})
    if job['status'] in ('failed', 'completed', 'cancelled', 'waiting_review'):
        break
    time.sleep(0.5)
print('after restart: status', job['status'], '| attempts', job['attempts'], '| fencing', job['fencing'], '| error', (job['error'] or {}).get('code'))
late = queue.complete(db, old['job_id'], old['token'])
print('old worker tries to complete with its stale token', old['token'], ':', 'accepted' if late else 'refused')
final = job['status'] in ('failed', 'completed', 'cancelled', 'waiting_review')
ok = final and job['attempts'] >= 2 and job['fencing'] > old['token'] and not late
raise SystemExit(0 if ok else 1)
"
}

duplicate_logical_key_is_one_job() {
  in_api "
from app.db import get_db
from app.jobs import queue
db = get_db()
job, created = queue.enqueue(db, 'collect', '$CHECK_KEY')
count = db.ai_jobs.count_documents({'logical_key': '$CHECK_KEY'})
print('second enqueue created a job:', created, '| jobs with this key:', count)
raise SystemExit(0 if not created and count == 1 else 1)
"
}

remove_check_job() {
  in_api "
from app.db import get_db
print('removed', get_db().ai_jobs.delete_many({'logical_key': '$CHECK_KEY'}).deleted_count, 'check job')
"
}

# ---------- Negative checks ----------

live_mode_without_secrets() {
  docker compose run --rm --no-deps -e APP_MODE=live -e SESSION_SECRET= -e REVALIDATION_SECRET= api python -m app.cli check-config
}

validator_rejects_bad_user() { # a copy of the real user record, differing only in its role
  in_api "
from pymongo.errors import WriteError
from app.db import get_db
from app.ids import new_id
users = get_db().users
doc = users.find_one({'email': '$COORDINATOR'})
doc.update(_id=new_id('usr'), email='step03-check@example.invalid', display_name='Step 03 check')
try:
    users.insert_one(dict(doc))
except WriteError as exc:
    print('the unchanged copy was refused, so this check proves nothing:', exc.details.get('errInfo'))
    raise SystemExit(3)
users.delete_one({'_id': doc['_id']})
print('an unchanged copy of the record is accepted (then removed)')
doc['roles'] = ['superuser']
try:
    users.insert_one(dict(doc))
except WriteError as exc:
    unmet = exc.details['errInfo']['details']['schemaRulesNotSatisfied']
    print('with roles [superuser]: rejected:', exc.details.get('errmsg'), '| rule not met:', unmet)
    raise SystemExit(1)
users.delete_one({'_id': doc['_id']})
print('with roles [superuser]: accepted (the validator did not stop it)')
"
}

stale_api_types() {
  cp -R contracts/v1 "$T/v1"
  cp web/lib/api-schema.d.ts "$T/api-schema.d.ts"
  "$PY" - "$T/v1/openapi.json" <<'EOF'
import json, sys
spec = json.load(open(sys.argv[1]))
spec["paths"]["/v1/auth/me"]["get"]["summary"] = "Changed without regenerating the web types"
json.dump(spec, open(sys.argv[1], "w"), indent=2)
EOF
  (cd web && pnpm exec openapi-typescript "$T/v1/openapi.json" -o "$T/api-schema.d.ts" --check)
}

# ---------- Hygiene ----------

env_file_private() {
  git check-ignore -q .env && echo ".env is git-ignored" || { echo ".env is NOT ignored"; return 1; }
  [ -z "$(git ls-files .env)" ] && echo ".env is not tracked" || { echo ".env is tracked"; return 1; }
  local mode
  mode=$(stat -f '%Lp' .env 2>/dev/null || stat -c '%a' .env)
  echo ".env permissions: $mode"
  [ "$mode" = "600" ]
}

no_tracked_secrets_or_env() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$|(^|/)\.venv/|(^|/)node_modules/|(^|/)\.next/')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env, .DS_Store, .venv, node_modules or .next tracked"
}

secrets_not_in_repo_or_logs() { # values come from .env; only names are printed
  docker compose logs --no-color > "$T/compose.log" 2>&1
  local name value hit found=0
  for name in SEED_USER_PASSWORD SESSION_SECRET REVALIDATION_SECRET ANTHROPIC_API_KEY; do
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

ports_on_loopback_only() {
  local out
  out=$(docker compose ps --format '{{.Service}} {{.Ports}}')
  echo "$out"
  ! echo "$out" | grep -E '0\.0\.0\.0:[0-9]+->|\[::\]:[0-9]+->' > /dev/null
}

repo_is_private_on_main() {
  local value
  value=$(gh repo view --json visibility,defaultBranchRef -q '.visibility + " " + .defaultBranchRef.name') || return 2
  echo "$value"
  [ "$value" = "PRIVATE main" ]
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

COORDINATOR=deepesh.gupta@client-site.example
SEED_PASSWORD=$(env_value SEED_USER_PASSWORD)

exec 3>&1 >"$LOG" 2>&1

echo "Step 03 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | uv $($UV --version 2>/dev/null | cut -d' ' -f2)"
echo "docker:     $(docker version --format '{{.Server.Version}}' 2>/dev/null) | compose $(docker compose version --short 2>/dev/null)"
echo "seeded password in .env: $([ -n "$SEED_PASSWORD" ] && echo present || echo MISSING) (value not shown)"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites (127 tests)" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: Step 02 contract checker" 0 "$PY" scripts/check_contracts.py

expect "UC-17: stack builds and every service is healthy" 0 docker compose up -d --build --wait
expect "UC-17: long-running services up; one-shot setup exited 0" 0 services_running
expect "UC-17: MongoDB replica set rs0 initialised, primary" 0 replica_set_primary
expect "UC-17: API readiness (replica set primary reachable)" 0 api_ready

expect "UC-18: repeating database setup changes nothing" 0 setup_db_is_a_no_op
expect "UC-18: no duplicate indexes" 0 no_duplicate_indexes
expect "UC-18: seeding projects twice; second run all unchanged" 0 seed_projects_twice
expect "UC-18: five projects with unique slugs stored" 0 five_projects_stored
expect "UC-18: seeding users again leaves the coordinator unchanged" 0 seed_users_repeat

expect "Backend: ruff lint" 0 bash -c "cd backend && $UV run ruff check ."
expect "Backend: ruff format" 0 bash -c "cd backend && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-18..UC-23: backend tests against the Compose replica set" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"

expect "Web: eslint" 0 bash -c "cd web && pnpm -s lint"
expect "Web: route types and TypeScript" 0 bash -c "cd web && pnpm -s typecheck"
expect "Web: generated API types match OpenAPI" 0 bash -c "cd web && pnpm -s check:api"
expect "Web: unit tests" 0 bash -c "cd web && pnpm -s test"
expect "Web: production build" 0 bash -c "cd web && pnpm -s build"

expect "UC-19: signed-out console redirects to login" 0 signed_out_console_redirects
expect "UC-19: signed-out API call is 401" 0 signed_out_api_is_401
expect "UC-19: wrong password is 401" 0 wrong_password_is_401
expect "UC-19: sign-in sets HttpOnly session and CSRF cookies" 0 login_sets_cookies
expect "UC-19: /v1/auth/me shows the coordinator's five roles" 0 me_has_all_roles
expect "UC-22: console shows the user, fixture banner and 5 catalogue projects" 0 console_shows_user_and_projects
expect "UC-22: operations: 11 connectors, all access_pending" 0 operations_lists_connectors
expect "UC-22: public page is the empty state, noindex" 0 public_page_empty_and_noindex
expect "UC-19: logout without CSRF 403; with CSRF 204; old cookie 401" 0 logout_needs_csrf
expect "UC-19: repeated failed logins are rate limited (429)" 0 login_rate_limited

expect "UC-20: a claimed job survives a real worker restart; the stale worker is refused" 0 job_survives_worker_restart
expect "UC-20: the same logical key never makes a second job" 0 duplicate_logical_key_is_one_job
expect "UC-20: remove the check job" 0 remove_check_job

expect "UC-21: model smoke test (real call with a key, otherwise skipped)" 0 smoke_model
expect "UC-23: configuration shows credential names only" 0 config_shows_names_only

expect_failure "N1: live mode without secrets refuses to start" "live mode needs SESSION_SECRET, REVALIDATION_SECRET" live_mode_without_secrets
expect_failure "N2: MongoDB validator rejects a user with an unknown role" "Document failed validation" validator_rejects_bad_user
expect_failure "N3: web types out of date with OpenAPI are caught" "Generated types are not up-to-date" stale_api_types

expect "Hygiene: .env ignored, untracked, permissions 600" 0 env_file_private
expect "Hygiene: nothing generated or secret is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: published ports bound to 127.0.0.1 only" 0 ports_on_loopback_only
expect "Hygiene: GitHub repo is private, default branch main" 0 repo_is_private_on_main
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
