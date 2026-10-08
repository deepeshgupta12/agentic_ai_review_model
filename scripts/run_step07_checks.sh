#!/usr/bin/env bash
# Step 07 checks: Steps 01-06 regression, backend and web gates, and the evidence layer on the Compose stack: the
# new collections, origin clusters (the scheduled job, then stable on a repeat), context windows for older evidence,
# the embedder (bge-m3 int8, pinned and checked) and the scheduled embedding of every evidence span, the evidence rules
# on the real stored data, hybrid retrieval on the real project evidence (no other project's and no ineligible
# results), the retrieval benchmark for keyword, vector and hybrid ranking, and hygiene.
# Output is printed and saved to logs/step-07/checks-<UTC time>.log. Secret values are read from .env but never
# printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step07_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in. No Claude call and no Whisper run are needed for
# Step 07. The first start of the embedder downloads the pinned model (568 MB) into a volume.

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

embedder_ready() {
  docker inspect agentic_ai_review_model-embedder-1 --format 'embedder memory limit {{.HostConfig.Memory}} bytes, oom_score_adj {{.HostConfig.OomScoreAdj}}, restart {{.HostConfig.RestartPolicy.Name}}'
  docker stats --no-stream --format 'embedder memory in use: {{.MemUsage}}' agentic_ai_review_model-embedder-1
  docker compose exec -T api python - <<'EOF' || return 1
import httpx
from app.config import get_settings
from app.embeddings.client import HttpEmbedder, model_label
settings = get_settings()
health = httpx.get(settings.embedding_url + "/health", timeout=5).json()
print(f"  health: {health}")
import time
from app.db import get_db
embedder = HttpEmbedder(settings, timeout=settings.embedding_job_timeout_seconds)
long_text = max((d["text"] for d in get_db().ai_evidence_search.find({}, {"text": 1}).limit(200)), key=len, default="x " * 2000)
t = time.perf_counter(); embedder.embed([long_text]); long_s = time.perf_counter() - t
t = time.perf_counter(); embedder.embed(["when will I get possession"]); query_s = time.perf_counter() - t
print(f"  one {len(long_text)}-character evidence text: {long_s:.1f} s; one short query: {query_s:.2f} s")
vectors = embedder.embed(["possession date", "पज़ेशन मार्च 2027 में देने का वादा किया गया है।", "two covered parking slots"])
same, other = sum(a * b for a, b in zip(vectors[0], vectors[1])), sum(a * b for a, b in zip(vectors[0], vectors[2]))
print(f"  {len(vectors)} vectors of {len(vectors[0])}; possession (en) vs पज़ेशन (hi) {same:.2f}, vs parking {other:.2f}")
raise SystemExit(0 if health["ready"] and health["model"] == model_label(settings) and len(vectors[0]) == settings.embedding_dim and same > other and query_s < settings.embedding_query_timeout_seconds else 1)
EOF
  docker compose exec -T embedder sh -c 'echo "  swap allowed: $(cat /sys/fs/cgroup/memory.swap.max) bytes; swapped now: $(cat /sys/fs/cgroup/memory.swap.current) bytes"' 
  [ "$(docker inspect agentic_ai_review_model-embedder-1 --format '{{.HostConfig.Memory}}')" = 1610612736 ] \
    && [ "$(docker inspect agentic_ai_review_model-embedder-1 --format '{{.HostConfig.RestartPolicy.Name}}')" = on-failure ]
}

scheduler_embeds_evidence() {
  docker compose exec -T -e SINCE="$STAMP" api python - <<'EOF'
import os
import time
from datetime import UTC, datetime
from app.config import get_settings
from app.db import get_db
from app.embeddings.jobs import pending_query
from app.evidence.retrieval import INDEX, sync_index
db, settings = get_db(), get_settings()
sync_index(db)
print(f"  search entries: {db[INDEX].count_documents({})}; waiting for a vector: {db[INDEX].count_documents(pending_query(settings))}")
started = time.monotonic()
deadline = started + 1500
while time.monotonic() < deadline:
    waiting = db[INDEX].count_documents(pending_query(settings))
    if waiting == 0:
        break
    time.sleep(15)
since = datetime.fromtimestamp(int(os.environ["SINCE"]), UTC)
jobs = {j["status"] for j in db.ai_jobs.find({"kind": "embed_evidence", "created_at": {"$gte": since}}, {"status": 1})}
waiting = db[INDEX].count_documents(pending_query(settings))
print(f"  embed_evidence jobs in this run: {sorted(jobs) or 'none needed'}; still waiting: {waiting}; waited {time.monotonic() - started:.0f} s")
raise SystemExit(0 if waiting == 0 and "failed" not in jobs else 1)
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
from app.config import get_settings
from app.embeddings.client import default_embedder
from app.evidence.eligibility import eligibility
from app.evidence.retrieval import search
db = get_db()
embedder = default_embedder(get_settings())
retrievers = set()
queries = ["possession", "price per sq ft", "road", "clubhouse", "maintenance", "पज़ेशन", ""]
bad, latencies = 0, []
for p in db.projects.find({}, {"slug": 1}).sort("slug", 1):
    counts = []
    for q in queries:
        r = search(db, p["_id"], q, limit=10, embedder=embedder)
        if q:
            retrievers.add((r["retriever"], r["degraded"]))
        latencies.append(r["elapsed_ms"])
        counts.append(len(r["items"]))
        for item in r["items"]:
            e = item["evidence"]
            if e["project_id"] != p["_id"] or not eligibility(db, e).eligible:
                bad += 1
    print(f"  {p['slug'][:44]:44} results per query {dict(zip(queries, counts))}")
ordered = sorted(latencies)
print(f"  {len(latencies)} searches; retriever {sorted(retrievers)}; latency p50 {ordered[len(ordered)//2]} ms, p95 {ordered[int(0.95*len(ordered))]} ms; results from another project or not eligible: {bad}")
top = search(db, db.projects.find_one({"slug": "conscient-parq-sector-80-gurgaon"})["_id"], "when will I get possession", limit=3, embedder=embedder)
for item in top["items"]:
    print(f"   rrf {item['score']} keyword {item['keyword_score']} cosine {item['similarity']} {item['evidence']['modality']:7} {item['evidence']['language']:7} {item['evidence']['excerpt_text'][:80]!r}")
raise SystemExit(1 if bad or retrievers != {("hybrid-rrf-v1", None)} else 0)
EOF
}

retrieval_benchmark() {
  docker compose exec -T api python -m app.cli eval-retrieval --save > "$T/retrieval.json"
  local code=$?
  "$PY" - "$T/retrieval.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  synthetic: {r['dataset']['synthetic']}; {r['documents']} posts, {r['queries']} queries; embedded {r['embedded']}; saved as {r['saved_as']}")
for mode, x in r["by_retriever"].items():
    print(f"  {x['retriever']:16} recall@10 {x['recall_at_10']} MRR@10 {x['mrr_at_10']} by kind {x['recall_at_10_by_kind']}")
    print(f"  {'':16} wrong-project {x['wrong_project_results']}, withdrawn {x['withdrawn_results']}, anchor errors {x['anchor_errors']}; latency p50 {x['latency_ms_p50']} ms, p95 {x['latency_ms_p95']} ms")
print(f"  queries by kind {r['queries_by_kind']}")
for row in r["rows"]:
    if row["missed"] or (row["rank_of_first_hit"] or 99) > 1:
        print(f"  hybrid: {row['id']} {row['kind']:16} {row['query']!r} first hit at {row['rank_of_first_hit']}, missed {row['missed']}")
sys.exit(0 if "hybrid" in r["by_retriever"] else 1)
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
expect "Regression: contract checker (api 1.2.0, operations 1.4.0, sources 1.4.0; D49, D50, D51)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-52: backend tests against the Compose replica set (no real credentials)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Images build (including the embedder)" 0 docker compose build
expect "MongoDB is healthy again after the builds" 0 mongodb_healthy
expect "Stack starts and every service is healthy" 0 docker compose up -d --wait
expect "Long-running services up" 0 services_running
expect "Database setup adds the Step 07 collections and indexes; a repeat changes nothing" 0 setup_creates_step07_collections
expect "UC-47: the scheduler queues clustering for new evidence and the worker completes it" 0 scheduler_clusters_new_evidence
expect "UC-47: clustering again changes nothing (stable cluster IDs); joined copies listed" 0 clusters_are_stable
expect "UC-49: older evidence gets its context window once" 0 context_backfill_once
expect "D51: the embedder serves pinned bge-m3 int8 vectors (1.5 GB cap, no swap, kill priority, restart on failure; speed)" 0 embedder_ready
expect "UC-52: the scheduler queues embedding and the worker gives every evidence span its vector" 0 scheduler_embeds_evidence
expect "UC-49/51: the evidence rules hold on the real stored data (verify-evidence)" 0 evidence_rules_hold
expect "UC-50/52: hybrid retrieval on the real evidence of the five projects returns only that project's eligible evidence" 0 retrieval_on_real_evidence
expect "UC-50/52: retrieval benchmark, keyword, vector and hybrid (saved): no wrong-project, withdrawn or anchor errors" 0 retrieval_benchmark
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
