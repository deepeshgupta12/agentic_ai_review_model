#!/usr/bin/env bash
# Step 05 checks: Steps 01-04 regression, backend and web gates, and collection on the Compose stack: repeatable
# setup and seeding, source policies, runs and their event stream, stored sources with evidence offsets, connector
# health, negative checks, the collection rules checked on the real stored data, and hygiene.
# Nothing here starts a collection run or re-check, so no Brave or YouTube quota is used; the live runs are recorded
# separately under logs/step-05/. Output is printed and saved to logs/step-05/checks-<UTC time>.log. Secret values
# are read from .env but never printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step05_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in; SEED_USER_PASSWORD in .env; at least one
# collection run in the database (make collect). It starts the stack if needed and leaves it running.

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-05
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
  local method=$1 path=$2 body=${3:-} header=${4:-X-Check: step05}
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
  for name in mongodb api worker scheduler web; do
    if echo "$running" | grep -qx "$name"; then echo "$name running"; else echo "$name NOT running"; missing=1; fi
  done
  return $missing
}

setup_db_is_a_no_op() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup.json" || return 1
  "$PY" - "$T/setup.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
step05 = ["ai_source_policies", "ai_connector_state", "ai_connector_quota", "ai_fetch_log", "ai_availability_checks",
          "ai_runs", "ai_run_events"]
missing = [c for c in step05 if c not in report["collections"]]
changed = {n: e for n, e in report["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"{len(report['collections'])} collections, including the 7 used by Step 05; missing: {missing or 'none'}; changed on repeat: {changed or 'none'}")
sys.exit(1 if changed or missing else 0)
EOF
}

seeding_is_repeatable() {
  docker compose exec -T api python -m app.cli seed-projects > "$T/seed.json" || return 1
  docker compose exec -T api python -m app.cli seed-policies > "$T/policies.json" || return 1
  "$PY" - "$T/seed.json" "$T/policies.json" <<'EOF'
import json, sys
projects = json.load(open(sys.argv[1]))["projects"]
policies = json.load(open(sys.argv[2]))
print("projects:", [p["outcome"] for p in projects])
print("policies:", {p["family"]: f"v{p['policy_version']} {p['outcome']}" for p in policies})
ok = len(projects) == 5 and all(p["outcome"] == "unchanged" for p in projects)
sys.exit(0 if ok and all(p["outcome"] == "unchanged" for p in policies) else 1)
EOF
}

real_data_has_no_fixture_data() {
  docker compose exec -T api python -c "
from app.db import get_db
db = get_db()
names = sorted(p['project_name'] for p in db.projects.find())
fictional = [n for n in names if n in ('Quillon Residences', 'Tavira Vista', 'Zephyrine Crest', 'Verdalia Parq', 'Solvane Heights')]
fake_hosts = db.ai_sources.count_documents({'canonical_url': {'\$regex': r'\.(test|example)(/|$)'}})
print('catalogue:', ', '.join(names))
print('fictional projects:', fictional or 'none', '| sources on test or example hosts:', fake_hosts)
print('stored sources, links, evidence:', db.ai_sources.count_documents({}), db.ai_project_source_links.count_documents({}), db.ai_evidence.count_documents({}))
raise SystemExit(0 if len(names) == 5 and not fictional and fake_hosts == 0 else 1)
"
}

# ---------- API through the web app ----------

sign_in() {
  rm -f "$JAR"
  local code
  code=$(EMAIL=deepesh.gupta@client-site.example PASSWORD="$SEED_PASSWORD" "$PY" -c \
    'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))' \
    | curl -s -o "$T/body" -w '%{http_code}' -c "$JAR" -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login")
  echo "HTTP $code (expected 200)"
  [ "$code" = 200 ]
}

policies_listed() {
  [ "$(api_json GET '/v1/admin/source-policies?limit=100')" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/PolicyPage" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
items = json.load(open(sys.argv[1]))["items"]
latest = {}
for p in items:
    if p["family"] not in latest or p["policy_version"] > latest[p["family"]]["policy_version"]:
        latest[p["family"]] = p
for family, p in sorted(latest.items()):
    print(f"  {family:22} v{p['policy_version']} collect={p['collection_allowed']} ai={p['ai_processing_allowed']} hosts={len(p['hosts'])}")
web = latest["web_public_pages"]
ok = web["policy_version"] == 4 and len(web["hosts"]) == 62 and "client-site.example" not in web["hosts"] and "competitor_portals" in latest
sys.exit(0 if ok else 1)
EOF
}

runs_listed_and_read() {
  local id run
  id=$(project_id dlf-privana-sector-76-gurgaon)
  [ "$(api_json GET "/v1/projects/$id/runs")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/RunPage" || return 1
  run=$(latest_run "$id")
  [ "$(api_json GET "/v1/runs/$run")" = 200 ] || return 1
  contract_ok "operations.schema.json#/\$defs/WorkflowRun" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
run = json.load(open(sys.argv[1]))
print(f"  {run['id']}: {run['stage']}, window {run['window']['from'][:10]} to {run['window']['to'][:10]}")
for c in run["coverage"]:
    print(f"  {c['connector_id']:18} {c['status']:18} queries {c['attempted_queries']:<3} fetched {c['fetched']:<4} matched {c['matched']:<4} {c['note'] or ''}")
statuses = {c["connector_id"]: c["status"] for c in run["coverage"]}
ok = run["stage"] == "analysing" and statuses.get("brave_search") == "complete_for_query" and "youtube_data_api" in statuses
sys.exit(0 if ok else 1)
EOF
}

run_events_stream_and_resume() {
  local id run first
  id=$(project_id sobha-crescent-sector-63a-gurgaon)
  run=$(latest_run "$id")
  curl -s --max-time 40 -b "$JAR" -D "$T/headers" -o "$T/events" "$WEB/v1/runs/$run/events"
  grep -qi '^content-type: text/event-stream' "$T/headers" || { echo "not an event stream"; return 1; }
  first=$(awk '/^id: /{print $2; exit}' "$T/events" | tr -d '\r')
  curl -s --max-time 40 -b "$JAR" -H "Last-Event-ID: $first" -o "$T/resumed" "$WEB/v1/runs/$run/events"
  "$PY" - "$T/events" "$T/resumed" <<'EOF'
import json, sys
def events(path):
    out = []
    for block in open(path).read().strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "id" in fields:
            out.append(fields)
    return out
full, resumed = events(sys.argv[1]), events(sys.argv[2])
sys.path.insert(0, "scripts")
import contract_tools as ct
contracts = ct.Contracts()
bad = [e["id"] for e in full if contracts.errors(json.loads(e["data"]), "api.schema.json#/$defs/RunEvent")]
print("events:", [e["event"] for e in full])
print("resumed after the first:", len(resumed), "events; contract errors:", bad or "none")
ok = full and full[-1]["event"] == "completed" and [e["id"] for e in resumed] == [e["id"] for e in full[1:]] and not bad
sys.exit(0 if ok else 1)
EOF
}

sources_listed_with_detail() {
  local id source
  id=$(project_id m3m-antalya-hills-sector-79-gurgaon)
  [ "$(api_json GET "/v1/projects/$id/sources?connector_id=web_fetch&limit=5")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/SourcePage" || return 1
  source=$("$PY" -c 'import json, sys; items = json.load(open(sys.argv[1]))["items"]; print(items[0]["source"]["id"] if items else "")' "$T/body")
  [ -n "$source" ] || { echo "no web page listed"; return 1; }
  [ "$(api_json GET "/v1/sources/$source/revisions/1")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/SourceRevisionDetail" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
s = d["source"]
print(f"  {s['canonical_url']} | {s['capture_level']} | date {s['publication_date']['status']} | policy {s['policy']['family']} v{s['policy']['policy_version']}")
print(f"  evidence spans: {len(d['evidence'])}; eligible: {sum(1 for e in d['evidence'] if e['eligible'])}; text shown: {d['permitted_text'] is not None}")
views = [e["anchor_view"] for e in d["evidence"] if e.get("anchor_view")]
ok = all(v["utf16_end"] >= v["utf16_start"] for v in views)
sys.exit(0 if ok else 1)
EOF
}

connector_health() {
  [ "$(api_json GET /v1/connectors/health)" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/ConnectorHealthList" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
rows = {r["connector_id"]: r for r in json.load(open(sys.argv[1]))["connectors"]}
for cid in ("anthropic", "brave_search", "web_fetch", "youtube_data_api", "firecrawl", "reddit_api"):
    r = rows[cid]
    print(f"  {cid:18} {r['status']:15} last success {r['last_success_at']} quota {r['quota']['used']}/{r['quota']['limit']}")
live = all(rows[c]["status"] == "live" for c in ("anthropic", "brave_search", "web_fetch", "youtube_data_api"))
sys.exit(0 if live and rows["brave_search"]["quota"]["used"] and rows["firecrawl"]["status"] == "access_pending" else 1)
EOF
}

# ---------- Negative checks ----------

run_needs_an_idempotency_key() {
  local id code
  id=$(project_id conscient-parq-sector-80-gurgaon)
  code=$(api_json POST "/v1/projects/$id/runs" '{"window_days": 30, "connectors": null}')
  echo "startRun without Idempotency-Key: HTTP $code"
  [ "$code" = 422 ]
}

run_refuses_a_connector_not_enabled() {
  local id code
  id=$(project_id conscient-parq-sector-80-gurgaon)
  code=$(api_json POST "/v1/projects/$id/runs" '{"window_days": 30, "connectors": ["reddit_api"]}' "Idempotency-Key: step05-check-$STAMP")
  echo "startRun with reddit_api, which no project enables: HTTP $code"
  [ "$code" = 422 ] && error_code_is validation_failed
}

cancel_unknown_run() {
  local code
  code=$(api_json POST /v1/runs/run_01K0000000000000000000000Z/cancel '{"reason": "check"}')
  echo "cancel an unknown run: HTTP $code"
  [ "$code" = 404 ]
}

withdrawal_needs_a_key() {
  local code
  code=$(api_json POST /v1/sources/src_01K0000000000000000000000Z/withdrawals '{"scope": "source_revision", "revision": 1, "reason": "check"}')
  echo "withdrawSource without Idempotency-Key: HTTP $code"
  [ "$code" = 422 ]
}

policy_version_needs_a_complete_body() {
  local code
  code=$(api_json POST /v1/admin/source-policies '{"family": "web_public_pages", "hosts": []}')
  echo "an incomplete policy version: HTTP $code"
  [ "$code" = 422 ]
}

database_refuses_an_unknown_job_kind() {
  docker compose exec -T api python -c "
from pymongo.errors import WriteError
from app.db import get_db, utcnow
from app.ids import new_id
now = utcnow()
db = get_db()
doc = {'_id': new_id('job'), 'logical_key': 'check:unknown-kind', 'kind': 'evaluate', 'run_id': None, 'project_id': None,
       'status': 'queued', 'attempts': 0, 'max_attempts': 1, 'next_attempt_at': now, 'deadline': None, 'lease': None,
       'checkpoint_id': None, 'error': None, 'fencing': 0, 'cancel_requested': False, 'created_at': now, 'updated_at': now}
with db.client.start_session() as session:  # the same record with a valid kind is accepted, then rolled back
    session.start_transaction()
    db.ai_jobs.insert_one(doc, session=session)
    session.abort_transaction()
print('with kind evaluate: accepted (rolled back)')
doc['kind'] = 'scrape_everything'
try:
    db.ai_jobs.insert_one(doc)
except WriteError as exc:
    print('refused:', exc.details.get('errmsg'))
    raise SystemExit(0)
db.ai_jobs.delete_one({'_id': doc['_id']})
print('accepted (the validator did not stop it)')
raise SystemExit(1)
"
}

# ---------- Collection rules on the real data ----------

collection_rules_hold() {
  docker compose exec -T api python -m app.cli verify-collection > "$T/verify.json"
  local code=$?
  "$PY" - "$T/verify.json" <<'EOF'
import json, sys
for r in json.load(open(sys.argv[1])):
    print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['check']:62} looked at {r['looked_at']:<5} broken {r['broken']} {r['examples'] or ''}")
EOF
  return $code
}

no_collect_job_failed() {
  docker compose exec -T api python -c "
from collections import Counter
from app.db import get_db
db = get_db()
jobs = Counter((j['kind'], j['status']) for j in db.ai_jobs.find({'kind': {'\$in': ['collect', 'check_availability', 'erase_payloads', 'invalidate_dependencies']}}))
for (kind, status), n in sorted(jobs.items()):
    print(f'  {kind:24} {status:10} {n}')
runs = Counter(r['stage'] for r in db.ai_runs.find())
print('  runs by stage:', dict(runs))
raise SystemExit(1 if any(s == 'failed' for (_, s) in jobs) or runs.get('collecting') else 0)
"
}

# ---------- Hygiene ----------

no_tracked_secrets_or_env() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$|(^|/)\.venv/|(^|/)node_modules/|(^|/)\.next/')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env, .DS_Store, .venv, node_modules or .next tracked"
}

secrets_not_in_repo_or_logs() {
  docker compose logs --no-color > "$T/compose.log" 2>&1
  local name value hit found=0
  for name in SEED_USER_PASSWORD SESSION_SECRET REVALIDATION_SECRET ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY YOUTUBE_API_KEY; do
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

echo "Step 05 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

expect "Regression: Step 01 validator (registry: four connectors live, each with its evidence log)" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: contract checker (operations 1.1.0 with check_availability, D44)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-40: backend tests against the Compose replica set (no real credentials)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Stack builds and every service is healthy" 0 docker compose up -d --build --wait
expect "Long-running services up" 0 services_running
expect "UC-33: repeating database setup changes nothing" 0 setup_db_is_a_no_op
expect "UC-33: seeding projects and policies again changes nothing" 0 seeding_is_repeatable
expect "Hygiene: the real data holds the five projects and no fixture data" 0 real_data_has_no_fixture_data

expect "Sign in through the web app" 0 sign_in
expect "UC-33: source policies (contract); web allow-list v4 with 62 hosts, client-site.example not on it (D41)" 0 policies_listed
expect "UC-40: runs for DLF Privana (contract) and the latest run's coverage (contract)" 0 runs_listed_and_read
expect "UC-40: run events as a server-sent stream, resumed with Last-Event-ID" 0 run_events_stream_and_resume
expect "UC-40: web pages for M3M Antalya Hills (contract) and one revision with its evidence (contract)" 0 sources_listed_with_detail
expect "UC-40: connector health (contract); anthropic, brave_search, web_fetch, youtube_data_api live" 0 connector_health

expect "N1: a run needs an Idempotency-Key (422)" 0 run_needs_an_idempotency_key
expect "N2: a run naming a connector the project does not enable is refused (422)" 0 run_refuses_a_connector_not_enabled
expect "N3: cancelling an unknown run (404)" 0 cancel_unknown_run
expect "N4: a withdrawal needs an Idempotency-Key (422)" 0 withdrawal_needs_a_key
expect "N5: an incomplete policy version is refused (422)" 0 policy_version_needs_a_complete_body
expect "N6: MongoDB refuses a job kind outside the contract" 0 database_refuses_an_unknown_job_kind

expect "UC-34..UC-39: the collection rules hold on the real stored data (verify-collection)" 0 collection_rules_hold
expect "UC-38: no collection, re-check, erasure or invalidation job failed; no run left collecting" 0 no_collect_job_failed

expect "Hygiene: nothing generated or secret is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
