#!/usr/bin/env bash
# Step 06 checks: Steps 01-05 regression, backend and web gates, and video transcripts on the Compose stack: the
# media worker (its own image and limits), repeatable setup and seeding, the spoken-content policy, the media
# library API, the synthetic speech check with the real Whisper model, the A04 translation check (one Claude call),
# a bounded live transcription attempt on real project videos, the collection rules on stored data, and hygiene.
# Output is printed and saved to logs/step-06/checks-<UTC time>.log. Secret values are read from .env but never
# printed. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step06_checks.sh
#
# Needs Docker, uv, pnpm, Node.js and Python 3.10+; `gh` signed in; SEED_USER_PASSWORD and ANTHROPIC_API_KEY in
# .env. The speech check takes several minutes (Whisper on the CPU). The live attempt queues at most 5 videos, once
# per day; while youtube.com is unreachable (I17) they end metadata-only with the reason recorded.

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-06
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
  local method=$1 path=$2 body=${3:-} header=${4:-X-Check: step06}
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

worker_roles() {
  local general media
  general=$(docker compose logs worker 2>/dev/null | grep '"worker started"' | tail -1)
  media=$(docker compose logs media-worker 2>/dev/null | grep '"worker started"' | tail -1)
  echo "worker:       $(echo "$general" | grep -o '"role": "[a-z]*"')"
  echo "media-worker: $(echo "$media" | grep -o '"role": "[a-z]*"') $(echo "$media" | grep -o '"kinds": \[[^]]*\]')"
  docker inspect agentic_ai_review_model-media-worker-1 --format 'media-worker memory limit {{.HostConfig.Memory}} bytes, oom_score_adj {{.HostConfig.OomScoreAdj}}'
  docker inspect agentic_ai_review_model-mongodb-1 --format 'mongodb oom_score_adj {{.HostConfig.OomScoreAdj}}'
  echo "$general" | grep -q '"role": "general"' && echo "$media" | grep -q '"kinds": \["process_media"\]' \
    && [ "$(docker inspect agentic_ai_review_model-media-worker-1 --format '{{.HostConfig.Memory}}')" = 2147483648 ]
}

setup_db_is_a_no_op() {
  docker compose exec -T api python -m app.cli setup-db > "$T/setup.json" || return 1
  "$PY" - "$T/setup.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1]))
changed = {n: e for n, e in report["collections"].items() if e["created"] or e["validator"] != "unchanged" or e["indexes_created"]}
print(f"{len(report['collections'])} collections, ai_media_segments present: {'ai_media_segments' in report['collections']}; changed on repeat: {changed or 'none'}")
sys.exit(1 if changed or "ai_media_segments" not in report["collections"] else 0)
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
versions = {p["family"]: p["policy_version"] for p in policies}
ok = all(p["outcome"] == "unchanged" for p in projects + policies)
sys.exit(0 if ok and versions["spoken_video_content"] == 2 and versions["youtube"] == 3 else 1)
EOF
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

spoken_policy() {
  [ "$(api_json GET '/v1/admin/source-policies?limit=100')" = 200 ] || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
items = json.load(open(sys.argv[1]))["items"]
latest = {}
for p in items:
    if p["family"] not in latest or p["policy_version"] > latest[p["family"]]["policy_version"]:
        latest[p["family"]] = p
spoken, youtube = latest["spoken_video_content"], latest["youtube"]
print(f"  spoken_video_content v{spoken['policy_version']}: collect={spoken['collection_allowed']} ai={spoken['ai_processing_allowed']} retention={spoken['retention_days']}")
for c in spoken["conditions"]:
    print("   -", c)
print(f"  youtube v{youtube['policy_version']}: {youtube['conditions'][1]}")
ok = spoken["policy_version"] == 2 and spoken["collection_allowed"] and "D33" in spoken["basis"] and youtube["policy_version"] == 3
sys.exit(0 if ok else 1)
EOF
}

media_library() {
  local id
  id=$(project_id m3m-antalya-hills-sector-79-gurgaon)
  [ "$(api_json GET "/v1/projects/$id/media?limit=100")" = 200 ] || return 1
  contract_ok "api.schema.json#/\$defs/MediaPage" || return 1
  "$PY" - "$T/body" <<'EOF'
import json, sys
from collections import Counter
items = json.load(open(sys.argv[1]))["items"]
print(f"  {len(items)} videos; access: {dict(Counter(i['source']['media']['access_status'] for i in items))}; formats: {dict(Counter(i['source']['media']['format'] for i in items))}")
print(f"  with transcript windows: {sum(1 for i in items if i['segments'])}")
sys.exit(0 if items else 1)
EOF
  local code
  code=$(api_json GET "/v1/projects/$id/media?format=sideways")
  echo "an unknown format filter: HTTP $code (expected 422)"
  [ "$code" = 422 ]
}

# ---------- Speech and language ----------

speech_check() {
  docker compose exec -T media-worker python -m app.cli eval-media --save > "$T/eval-media.json" 2> "$T/eval-media.err" || { tail -5 "$T/eval-media.err"; return 1; }
  "$PY" - "$T/eval-media.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  model {r['model_size']}; synthetic: {r['dataset']['synthetic']}; mean WER {r['mean_wer']} {r['mean_wer_by_language']}; key facts kept {r['facts_kept']}; saved as {r['saved_as']}")
for row in r["rows"]:
    print(f"  {row['id']} {row['language']:7} WER {row['wer']:<6} facts {row['facts_kept']}/{row['facts']} speed {row['real_time_factor']}x | {row['transcript'][:70]}")
kept, total = (int(x) for x in r["facts_kept"].split("/"))
sys.exit(0 if r["dataset"]["synthetic"] and r["saved_as"] and kept / total >= 0.8 else 1)
EOF
}

language_check() {
  docker compose exec -T api python -m app.cli eval-language --save > "$T/eval-language.json" || return 1
  "$PY" - "$T/eval-language.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  model {r['model']}; outcome {r['outcome']}; kept by the backend {r['kept_by_backend']}; English facts kept {r['facts_kept']}; tokens {r['usage']['input_tokens']}/{r['usage']['output_tokens']}")
for row in r["rows"]:
    print(f"  {row['id']} {'kept' if row['kept_by_backend'] else 'REJECTED: ' + str(row['rejection'])} | {row['translation'][:80]}")
kept, total = (int(x) for x in r["kept_by_backend"].split("/"))
facts, all_facts = (int(x) for x in r["facts_kept"].split("/"))
sys.exit(0 if r["outcome"] == "completed" and kept / total >= 0.8 and facts / all_facts >= 0.9 else 1)
EOF
}

live_transcription_attempt() {
  docker compose exec -T api python -m app.cli transcribe-videos --limit 5 --wait 900 > "$T/transcribe.json" || return 1
  "$PY" - "$T/transcribe.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
print("  queued:", r["queued"])
print("  videos by status:", r["videos_by_status"])
print("  refusal or error reasons so far:", r["refusal_or_error_reasons"])
print("  transcript windows:", r["segments"], "| speech evidence:", r["speech_evidence"])
pending = [k for k in r["videos_by_status"] if k.startswith("access_pending")]
sys.exit(1 if pending else 0)
EOF
}

media_jobs_settled() {
  docker compose exec -T api python -c "
from collections import Counter
from app.db import get_db
db = get_db()
jobs = Counter(j['status'] for j in db.ai_jobs.find({'kind': 'process_media'}))
print('  process_media jobs:', dict(jobs))
raise SystemExit(1 if jobs.get('running') or jobs.get('queued') or jobs.get('failed') else 0)
"
}

collection_rules_hold() {
  docker compose exec -T api python -m app.cli verify-collection > "$T/verify.json"
  local code=$?
  "$PY" - "$T/verify.json" <<'EOF'
import json, sys
for r in json.load(open(sys.argv[1])):
    print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['check']:72} looked at {r['looked_at']:<5} broken {r['broken']}")
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
SEED_PASSWORD=$(env_value SEED_USER_PASSWORD)

exec 3>&1 >"$LOG" 2>&1

echo "Step 06 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv); backend $(cd backend && $UV run python --version 2>&1)"
echo "node:       $(node --version 2>/dev/null) | pnpm $(pnpm --version 2>/dev/null) | docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) | Docker VM memory $(docker info --format '{{.MemTotal}}' 2>/dev/null) bytes"

expect "Regression: Step 01 validator" 0 python3 scripts/validate_inputs.py
expect "Regression: Step 01-02 use-case suites" 0 "$PY" -m unittest discover -s scripts/tests -q
expect "Regression: contract checker (sources 1.3.0, operations 1.2.0, D47)" 0 "$PY" scripts/check_contracts.py

expect "Backend: ruff lint and format" 0 bash -c "cd backend && $UV run ruff check . && $UV run ruff format --check ."
expect "Backend: mypy" 0 bash -c "cd backend && $UV run mypy"
expect "UC-17..UC-46: backend tests against the Compose replica set (no real credentials)" 0 bash -c "cd backend && $UV run pytest -q -p no:cacheprovider"
expect "Web: eslint, TypeScript, API types, unit tests" 0 bash -c "cd web && pnpm -s lint && pnpm -s typecheck >/dev/null && pnpm -s check:api && pnpm -s test >/dev/null && echo 'web gates OK'"

expect "Stack builds (including the media worker image) and every service is healthy" 0 docker compose up -d --build --wait
expect "Long-running services up, including media-worker" 0 services_running
expect "D48: worker roles, the media worker's 2 GB cap and kill priority; MongoDB protected" 0 worker_roles
expect "Repeating database setup changes nothing (ai_media_segments present)" 0 setup_db_is_a_no_op
expect "Seeding again changes nothing; spoken_video_content v2 and youtube v3" 0 seeding_is_repeatable

expect "Sign in through the web app" 0 sign_in
expect "D47: spoken_video_content v2 applies D33; youtube v3" 0 spoken_policy
expect "UC-45: media library for M3M Antalya Hills (contract); unknown filter refused (422)" 0 media_library

expect "UC-42: synthetic speech check with the real Whisper model in the media worker (saved)" 0 speech_check
expect "UC-46: A04 translation check, numbers and negation kept (one Claude call, saved)" 0 language_check
expect "UC-43 live: bounded transcription attempt on real project videos; every video ends with a recorded state" 0 live_transcription_attempt
expect "UC-43 live: no media job left running, queued or failed" 0 media_jobs_settled
expect "The collection and transcript rules hold on the real stored data (verify-collection)" 0 collection_rules_hold

expect "Hygiene: nothing generated, secret or downloaded is tracked" 0 no_tracked_secrets_or_env
expect "Hygiene: secret values absent from commits, service logs and logs/" 0 secrets_not_in_repo_or_logs
expect "Hygiene: latest CI run on main is not failing" 0 ci_not_failing

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
