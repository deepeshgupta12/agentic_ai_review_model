#!/usr/bin/env bash
# Step 04 checks: Steps 01-03 regression, backend and web gates, and project identity on the Compose stack:
# repeatable setup and seeding with construction status, the catalogue and configuration APIs through the web
# app, bounded query plans, dry-run matching on the real catalogue, the full identity path on the fictional
# catalogue in a scratch database (with the real worker), the identity evaluation, negative checks and hygiene.
# Output is printed and saved to logs/step-04/checks-<UTC time>.log. Secret values are read from .env but never
# printed. No made-up text is ever stored in the real catalogue. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step04_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in; SEED_USER_PASSWORD in .env.
# It starts the stack if needed and leaves it running (stop it with `make down`).

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-04
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

status_is() { # status_is <expected HTTP status> <curl arguments...>
  local want=$1 got
  shift
  got=$(curl -s -o "$T/body" -w '%{http_code}' "$@")
  echo "HTTP $got (expected $want)"
  [ "$got" = "$want" ]
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

api_json() { # api_json <METHOD> <path> [json body]: signed-in call through the web app with CSRF on mutations
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X "$method" -H 'Content-Type: application/json' \
      -H "X-CSRF-Token: $(csrf)" --data-binary "$body" "$WEB$path"
  else
    curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X "$method" "$WEB$path"
  fi
}

project_id() { # project_id <slug>
  docker compose exec -T api python -c "from app.db import get_db; print(get_db().projects.find_one({'slug': '$1'})['_id'])"
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
step04 = ["ai_sources", "ai_payloads", "ai_project_source_links", "ai_evidence", "ai_alias_proposals",
          "ai_review_decisions", "ai_evaluations", "ai_idempotency_keys"]
missing = [c for c in step04 if c not in report["collections"]]
changed = {n: e for n, e in report["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"{len(report['collections'])} collections, including the 8 added in Step 04; changed on repeat: {changed or 'none'}")
sys.exit(1 if changed or missing else 0)
EOF
}

seed_twice_with_statuses() {
  docker compose exec -T api python -m app.cli seed-projects > /dev/null || return 1
  docker compose exec -T api python -m app.cli seed-projects > "$T/seed.json" || return 1
  "$PY" - "$T/seed.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
for row in report["construction_status"]:
    print(f"  {row['project_slug']}: {row['applies_to']} -> {row['status']} ({row['outcome']})")
ok = len(report["projects"]) == 5 and all(p["outcome"] == "unchanged" for p in report["projects"])
ok = ok and len(report["construction_status"]) == 7 and all(r["outcome"] == "unchanged" for r in report["construction_status"])
print("second run: projects and status records unchanged" if ok else "second run changed something")
sys.exit(0 if ok else 1)
EOF
}

real_catalogue_has_no_fixture_data() {
  docker compose exec -T api python -c "
from app.db import get_db
db = get_db()
names = sorted(p['project_name'] for p in db.projects.find())
fictional = [n for n in names if n in ('Quillon Residences', 'Tavira Vista', 'Zephyrine Crest', 'Verdalia Parq', 'Solvane Heights')]
print('catalogue:', ', '.join(names))
print('fictional projects in the real catalogue:', fictional or 'none')
print('stored sources, links, evidence:', db.ai_sources.count_documents({}), db.ai_project_source_links.count_documents({}), db.ai_evidence.count_documents({}))
raise SystemExit(0 if len(names) == 5 and not fictional else 1)
"
}

# ---------- API through the web app ----------

sign_in() {
  rm -f "$JAR"
  EMAIL=deepesh.gupta@client-site.example PASSWORD="$SEED_PASSWORD" "$PY" -c \
    'import json, os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))' \
    | status_is 200 -c "$JAR" -X POST -H 'Content-Type: application/json' --data-binary @- "$WEB/v1/auth/login"
}

list_projects() {
  [ "$(api_json GET /v1/projects)" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/ProjectPage" || return 1
  "$PY" -c 'import json, sys; items = json.load(open(sys.argv[1]))["items"]; [print(" ", i["project"]["slug"], "| pending review:", i["pending_review"]) for i in items]; sys.exit(0 if len(items) == 5 else 1)' "$T/body"
}

project_detail_has_statuses() {
  local id
  id=$(project_id m3m-antalya-hills-sector-79-gurgaon)
  [ "$(api_json GET "/v1/projects/$id")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/ProjectDetail" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
config = json.load(open(sys.argv[1]))["config"]
records = {(r["applies_to"]["rera_id"] or "project"): r["status"] for r in config["construction_status"]}
for target, status in sorted(records.items()):
    print(f"  {target}: {status}")
aliases = [a["text"] for a in config["aliases"]]
print("  aliases:", ", ".join(aliases))
ok = records.get("GGM/650/382/2022/125") == "ready_to_move" and "GGM/833/565/2024/60" not in records
sys.exit(0 if ok else 1)
EOF
}

import_is_idempotent() {
  local body code
  body=$(cat contracts/five-project-input-template.json)
  code=$(curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X POST -H 'Content-Type: application/json' -H "X-CSRF-Token: $(csrf)" \
    --data-binary "$body" "$WEB/v1/projects/import")
  echo "without Idempotency-Key: HTTP $code"
  [ "$code" = 422 ] || return 1
  for attempt in first replay; do
    code=$(curl -s -o "$T/body-$attempt" -w '%{http_code}' -b "$JAR" -X POST -H 'Content-Type: application/json' \
      -H "X-CSRF-Token: $(csrf)" -H "Idempotency-Key: step04-check-$STAMP" --data-binary "$body" "$WEB/v1/projects/import")
    echo "$attempt with the key: HTTP $code"
    [ "$code" = 200 ] || return 1
  done
  cmp -s "$T/body-first" "$T/body-replay" && echo "replay returned the identical result" || return 1
  cp "$T/body-first" "$T/body" && contract_ok "api.schema.json#/\$defs/ImportResult" || return 1
  "$PY" -c 'import json, sys; rows = json.load(open(sys.argv[1]))["projects"]; print("created:", [r["created"] for r in rows]); sys.exit(0 if not any(r["created"] for r in rows) else 1)' "$T/body-first"
}

import_key_reused_with_a_different_body() {
  local body code
  body=$("$PY" -c 'import json; d = json.load(open("contracts/five-project-input-template.json")); d["projects"][0]["locality"] = "Sector 77"; print(json.dumps(d))')
  code=$(curl -s -o "$T/body" -w '%{http_code}' -b "$JAR" -X POST -H 'Content-Type: application/json' -H "X-CSRF-Token: $(csrf)" \
    -H "Idempotency-Key: step04-check-$STAMP" --data-binary "$body" "$WEB/v1/projects/import")
  echo "HTTP $code"
  [ "$code" = 409 ] && error_code_is idempotency_conflict
}

stale_config_write() {
  local id version
  id=$(project_id sobha-crescent-sector-63a-gurgaon)
  api_json GET "/v1/projects/$id" > /dev/null
  version=$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["config"]["version"])' "$T/body")
  local code
  code=$(api_json PATCH "/v1/projects/$id" "{\"expected_version\": $((version - 1)), \"negative_keywords\": []}")
  echo "PATCH at version $((version - 1)) while the config is at $version: HTTP $code"
  [ "$code" = 409 ] && error_code_is version_conflict
}

foreign_registration_refused() {
  local id version code
  id=$(project_id dlf-privana-sector-76-gurgaon)
  api_json GET "/v1/projects/$id" > /dev/null
  version=$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["config"]["version"])' "$T/body")
  code=$(api_json PATCH "/v1/projects/$id" "{\"expected_version\": $version, \"construction_status\": [{\"status\": \"ready_to_move\", \"applies_to\": {\"kind\": \"phase\", \"rera_id\": \"GGM/650/382/2022/125\"}, \"basis\": \"moderator\", \"as_of\": \"2026-09-28\", \"note\": null}]}")
  echo "a DLF Privana status record naming an M3M Antalya Hills registration: HTTP $code"
  [ "$code" = 422 ] && error_code_is validation_failed
}

aliases_not_patchable() {
  local id code
  id=$(project_id conscient-parq-sector-80-gurgaon)
  code=$(api_json PATCH "/v1/projects/$id" '{"expected_version": 1, "aliases": []}')
  echo "PATCH trying to replace aliases: HTTP $code"
  [ "$code" = 422 ] && error_code_is validation_failed
}

link_decision_needs_a_reason() {
  local code
  code=$(api_json POST /v1/project-source-links/lnk_01K00000000000000000000000/decisions \
    '{"action": "reject", "expected_version": 1, "reason": null, "split_segments": null, "remap_project_id": null, "phase_rera_id": null}')
  echo "reject without a reason: HTTP $code"
  [ "$code" = 422 ] && error_code_is validation_failed
}

alias_proposals_listed() {
  local id
  id=$(project_id dlf-privana-sector-76-gurgaon)
  [ "$(api_json GET "/v1/projects/$id/alias-proposals")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/AliasProposalPage" || return 1
  local code
  code=$(api_json POST /v1/alias-proposals/als_01K00000000000000000000000/decisions \
    '{"action": "approve", "mode": "standalone", "reason": null, "expected_version": 1}')
  echo "decision on an unknown proposal: HTTP $code"
  [ "$code" = 404 ]
}

database_refuses_an_unknown_link_status() {
  docker compose exec -T api python -c "
from pymongo.errors import WriteError
from app.db import get_db, utcnow
from app.ids import new_id
doc = {'_id': new_id('lnk'), 'project_id': new_id('prj'), 'source': {'id': new_id('src'), 'revision': 1},
       'segment_key': 'whole', 'segment_anchor': None, 'status': 'approved_by_model', 'phase': {'rera_id': None, 'certainty': 'unknown'},
       'match': {'method': 'identity_agent', 'rule_score': None, 'signals': [], 'matched_alias': None, 'rationale': 'model says yes'},
       'decided_by': None, 'superseded_by': [], 'version': 1, 'created_at': utcnow()}
try:
    get_db().ai_project_source_links.insert_one(doc)
except WriteError as exc:
    print('refused:', exc.details.get('errmsg'))
    raise SystemExit(0)
get_db().ai_project_source_links.delete_one({'_id': doc['_id']})
print('accepted (the validator did not stop it)')
raise SystemExit(1)
"
}

# ---------- Identity on the stack ----------

plans_for_all_projects() {
  docker compose exec -T api python -m app.cli plan-queries > "$T/plans.json" || return 1
  "$PY" - "$T/plans.json" <<'EOF'
import json, sys
plans = json.load(open(sys.argv[1]))
for p in plans:
    queries = p["plan"]["queries"]
    per = {}
    for q in queries:
        per[q["connector_id"]] = per.get(q["connector_id"], 0) + 1
    print(f"  {p['project_id']}: {len(queries)} queries {per} ({p['rules_version']})")
sys.exit(0 if len(plans) == 5 and all(p["plan"]["queries"] for p in plans) else 1)
EOF
}

dry_run_match() { # dry_run_match <text> <python expression over outcomes o>
  docker compose exec -T api python -m app.cli match-text --text "$1" > "$T/match.json" || return 1
  "$PY" - "$T/match.json" "$2" <<'EOF'
import json, sys
o = json.load(open(sys.argv[1]))
for row in o if isinstance(o, list) else []:
    print(f"  {row['project']}: {row['status']}, phase {row['phase']}, signals {row['signals']}")
if isinstance(o, str):
    print(" ", o)
sys.exit(0 if eval(sys.argv[2]) else 1)
EOF
}

fixture_smoke() {
  docker compose exec -T api python -m app.cli fixture-smoke-identity
}

evaluation() {
  docker compose exec -T api python -m app.cli eval-identity --save > "$T/eval.json"
  local code=$?
  "$PY" - "$T/eval.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"dataset {r['dataset']['name']} {r['dataset']['version']} (synthetic: {r['dataset']['synthetic']}), rules {r['rules']}")
for name, m in r["metrics"].items():
    print(f"  {name:32} {m['value']!s:7} n={m['n']:<3} {m['note']}")
print("target met:", r["auto_accept_precision_target_met"], "| saved as", r["saved_as"])
print("caution:", r["caution"])
EOF
  return $code
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

echo "Step 04 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites (127 tests)" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: contract checker (state machines 1.1 and journeys 1.1, D35)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-32: backend tests against the Compose replica set" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Stack builds and every service is healthy" 0 docker compose up -d --build --wait
expect "Long-running services up" 0 services_running
expect "UC-26: repeating database setup changes nothing (16 collections)" 0 setup_db_is_a_no_op
expect "UC-26: seeding twice; projects and 7 status records unchanged (I16)" 0 seed_twice_with_statuses
expect "Hygiene: the real catalogue holds the five projects and no fixture data" 0 real_catalogue_has_no_fixture_data

expect "Sign in through the web app" 0 sign_in
expect "UC-26: portfolio lists five projects (contract)" 0 list_projects
expect "UC-26: project detail with phase statuses; Antalya Phase II unknown (contract)" 0 project_detail_has_statuses
expect "UC-26: import needs an Idempotency-Key; the same key replays the result" 0 import_is_idempotent
expect "UC-29: alias proposals list (contract); unknown proposal 404" 0 alias_proposals_listed

expect "UC-30: bounded query plans for all five projects (DiscoveryPlan contract)" 0 plans_for_all_projects
expect "UC-27: dry run: 'DLF Privana West, Sector 76 Gurgaon' finds the West phase" 0 dry_run_match "DLF Privana West, Sector 76 Gurgaon" 'len(o) == 1 and o[0]["status"] == "auto_accepted" and o[0]["phase"]["rera_id"] == "GGM/819/551/2024/46"'
expect "UC-27: dry run: '3 BHK' never becomes M3M Antalya Hills 3" 0 dry_run_match "M3M Antalya Hills 3 BHK floors in Sector 79" 'len(o) == 1 and o[0]["phase"]["rera_id"] is None'
expect "UC-27: dry run: 'Parq' alone names nothing" 0 dry_run_match "Parq has a nice park" 'o == "no catalogue project is named in this text"'
expect "UC-28: full identity path on the fictional catalogue in a scratch database (real worker)" 0 fixture_smoke
expect "UC-32: identity evaluation, saved to ai_evaluations" 0 evaluation

expect "N1: an Idempotency-Key reused with a different body is refused (409)" 0 import_key_reused_with_a_different_body
expect "N2: a stale configuration write is refused (409)" 0 stale_config_write
expect "N3: a status record naming another project's registration is refused (422)" 0 foreign_registration_refused
expect "N4: aliases cannot be replaced through configuration (422)" 0 aliases_not_patchable
expect "N5: a link decision without a reason is refused (422)" 0 link_decision_needs_a_reason
expect "N6: MongoDB refuses a link status outside the contract" 0 database_refuses_an_unknown_link_status

expect "Hygiene: nothing generated or secret is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
