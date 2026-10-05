#!/usr/bin/env bash
# Step 07 checks: Steps 01-06 regression, backend and web gates, and the evidence layer on the Compose stack: the
# new collections, origin clusters (the scheduled job, then stable on a repeat), context windows for older evidence,
# the evidence rules on the real stored data, filtered retrieval on the real project evidence (no other project's
# and no ineligible results), the retrieval benchmark on the labelled synthetic set, and hygiene.
# Output is printed and saved to logs/step-07/checks-<UTC time>.log. Secret values are read from .env but never
# printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step07_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in; SEED_USER_PASSWORD in .env. No Claude call and
# no Whisper run are needed for Step 07.

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-07
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
  local method=$1 path=$2 body=${3:-} header=${4:-X-Check: step07}
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
  for name in mongodb api worker media-worker scheduler web; do
    if echo "$running" | grep -qx "$name"; then echo "$name running"; else echo "$name NOT running"; missing=1; fi
  done
  return $missing
}

setup_creates_step07_collections() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup1.json" || return 1
  docker compose exec -T api python -m app.cli setup-db > "$T/setup2.json" || return 1
  "$PY" - "$T/setup1.json" "$T/setup2.json" <<'EOF'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
wanted = ["ai_claims", "ai_findings", "ai_review_excerpts", "ai_content_revisions", "ai_evidence_search"]
present = [n for n in wanted if n in second["collections"]]
made = {n: e["indexes_created"] for n, e in first["collections"].items() if e["created"] or e["indexes_created"] or e["validator"] != "unchanged"}
changed = {n: e for n, e in second["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"first pass changed: {made or 'nothing (already set up)'}")
print(f"Step 07 collections present: {present}; changed on repeat: {changed or 'none'}")
sys.exit(0 if len(present) == len(wanted) and not changed else 1)
EOF
}

scheduler_clusters_new_evidence() {
  docker compose exec -T api python - <<'EOF'
import time
from app.db import get_db
db = get_db()
waiting = db.ai_evidence.count_documents({"origin_cluster": None, "excerpt_text": {"$type": "string"}})
print(f"  evidence waiting for a cluster: {waiting}")
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    jobs = list(db.ai_jobs.find({"kind": "cluster_origins"}, {"status": 1, "logical_key": 1}).sort("created_at", -1).limit(1))
    left = db.ai_evidence.count_documents({"origin_cluster": None, "excerpt_text": {"$type": "string"}})
    if jobs and jobs[0]["status"] == "completed" and left == 0:
        break
    time.sleep(10)
job = db.ai_jobs.find_one({"kind": "cluster_origins"}, sort=[("created_at", -1)])
left = db.ai_evidence.count_documents({"origin_cluster": None, "excerpt_text": {"$type": "string"}})
print(f"  latest clustering job: {job['logical_key'] if job else None} {job['status'] if job else ''}; still waiting: {left}")
raise SystemExit(0 if job and job["status"] == "completed" and left == 0 else 1)
EOF
}

clusters_are_stable() {
  docker compose exec -T api python -m app.cli cluster-origins > "$T/clusters.json" || return 1
  "$PY" - "$T/clusters.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  sources with evidence {r['sources']}; clusters {r['clusters']}; joined (copies of one origin) {r['joined']}; created {r['created']}, changed {r['changed']}, retired {r['retired']} on this repeat")
sys.exit(0 if r["created"] == r["changed"] == r["retired"] == 0 else 1)
EOF
  docker compose exec -T api python - <<'EOF'
from app.db import get_db
db = get_db()
for c in db.ai_origin_clusters.find({"members.1": {"$exists": True}}).limit(5):
    kinds = [db.ai_sources.find_one({"id": m["id"], "revision": m["revision"]}, {"source_kind": 1})["source_kind"] for m in c["members"]]
    print(f"  {c['_id']} v{c['version']} {c['method']}: {len(c['members'])} copies ({', '.join(kinds)})")
EOF
}

context_backfill_once() {
  docker compose exec -T api python -m app.cli add-evidence-context > "$T/ctx1.json" || return 1
  docker compose exec -T api python -m app.cli add-evidence-context > "$T/ctx2.json" || return 1
  "$PY" - "$T/ctx1.json" "$T/ctx2.json" <<'EOF'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
print(f"  first pass: {first}")
print(f"  repeat:     {second}")
sys.exit(0 if second["set"] == 0 else 1)
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

retrieval_on_real_evidence() {
  docker compose exec -T api python - <<'EOF'
import statistics
from app.db import get_db
from app.evidence.eligibility import eligibility
from app.evidence.retrieval import search
db = get_db()
queries = ["possession", "price per sq ft", "road", "clubhouse", "maintenance", "पज़ेशन", ""]
bad, latencies = 0, []
for p in db.projects.find({}, {"slug": 1}).sort("slug", 1):
    counts = []
    for q in queries:
        r = search(db, p["_id"], q, limit=10)
        latencies.append(r["elapsed_ms"])
        counts.append(len(r["items"]))
        for item in r["items"]:
            e = item["evidence"]
            if e["project_id"] != p["_id"] or not eligibility(db, e).eligible:
                bad += 1
    print(f"  {p['slug'][:44]:44} results per query {dict(zip(queries, counts))}")
ordered = sorted(latencies)
print(f"  {len(latencies)} searches; latency p50 {ordered[len(ordered)//2]} ms, p95 {ordered[int(0.95*len(ordered))]} ms; results from another project or not eligible: {bad}")
top = search(db, db.projects.find_one({"slug": "conscient-parq-sector-80-gurgaon"})["_id"], "possession", limit=3)
for item in top["items"]:
    print(f"   {item['score']:6} {item['evidence']['modality']:7} {item['evidence']['language']:7} {item['evidence']['excerpt_text'][:90]!r}")
raise SystemExit(1 if bad else 0)
EOF
}

retrieval_benchmark() {
  docker compose exec -T api python -m app.cli eval-retrieval --save > "$T/retrieval.json"
  local code=$?
  "$PY" - "$T/retrieval.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  synthetic: {r['dataset']['synthetic']}; {r['documents']} posts, {r['queries']} queries; retriever {r['retriever']}; saved as {r['saved_as']}")
print(f"  recall@10 {r['recall_at_10']}; by kind {r['recall_at_10_by_kind']} (queries {r['queries_by_kind']})")
print(f"  wrong-project results {r['wrong_project_results']}; withdrawn results {r['withdrawn_results']}; anchor errors {r['anchor_errors']}; latency p50 {r['latency_ms_p50']} ms, p95 {r['latency_ms_p95']} ms")
for row in r["rows"]:
    if row["missed"]:
        print(f"  missed: {row['id']} {row['kind']:16} {row['query']!r} -> {row['missed']}")
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

exec 3>&1 >"$LOG" 2>&1

echo "Step 07 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) | Docker VM memory $(docker info --format '{{.MemTotal}}' 2>/dev/null) bytes"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: contract checker (api 1.2.0, operations 1.3.0, sources 1.4.0; D49, D50)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-51: backend tests against the Compose replica set (no real credentials)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Stack builds and every service is healthy" 0 docker compose up -d --build --wait
expect "Long-running services up" 0 services_running
expect "Database setup adds the Step 07 collections and indexes; a repeat changes nothing" 0 setup_creates_step07_collections
expect "UC-47: the scheduler queues clustering for new evidence and the worker completes it" 0 scheduler_clusters_new_evidence
expect "UC-47: clustering again changes nothing (stable cluster IDs); joined copies listed" 0 clusters_are_stable
expect "UC-49: older evidence gets its context window once" 0 context_backfill_once
expect "UC-49/51: the evidence rules hold on the real stored data (verify-evidence)" 0 evidence_rules_hold
expect "UC-50: retrieval on the real evidence of the five projects returns only that project's eligible evidence" 0 retrieval_on_real_evidence
expect "UC-50: retrieval benchmark on the labelled synthetic set (saved): no wrong-project, withdrawn or anchor errors" 0 retrieval_benchmark
expect "Regression: the collection rules still hold (verify-collection)" 0 collection_rules_hold

expect "Hygiene: nothing generated, secret or downloaded is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
