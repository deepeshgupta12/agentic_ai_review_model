#!/usr/bin/env bash
# Step 02 checks: Step 01 regression, the full use-case suite, the contract checker,
# generated-file freshness, the JavaScript cross-check, six negative checks on a
# temporary copy of the repository (real files are never changed) and repository
# hygiene. Output is printed and saved to logs/step-02/checks-<UTC time>.log.
# Exit code 0 only if every check is OK.
#
#   bash scripts/run_step02_checks.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LOG_DIR=logs/step-02
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checks-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILED=0
PY="$ROOT/.venv/bin/python"

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
  echo "$out" | grep -F -- "$needle" || true
  if [ "$got" -ne 0 ] && echo "$out" | grep -qF -- "$needle"; then
    echo "--> OK (failed as expected, exit $got)"
  else
    echo "--> NOT OK (exit $got; expected a failure mentioning: $needle)"
    FAILED=1
  fi
}

fresh_copy() { # fresh_copy <dir>: repository copy for a negative check
  rm -rf "$1"
  mkdir -p "$1"
  rsync -a --exclude .git --exclude .venv --exclude logs "$ROOT/" "$1/"
}

edit_json() { # edit_json <file> <python statement changing d>
  "$PY" - "$1" "$2" <<'EOF'
import json, sys
path, change = sys.argv[1:3]
d = json.load(open(path, encoding="utf-8"))
exec(change)
json.dump(d, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
EOF
}

in_copy() { # in_copy <dir> <command...>: run a command inside a repository copy
  local dir=$1
  shift
  (cd "$dir" && "$@")
}

no_tracked_secrets_or_env() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$|^\.venv/')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env, .DS_Store or .venv tracked"
}

repo_is_private_on_main() {
  local value
  value=$(gh repo view --json visibility,defaultBranchRef -q '.visibility + " " + .defaultBranchRef.name') || return 2
  echo "$value"
  [ "$value" = "PRIVATE main" ]
}

# Tooling (D26): create the local environment on first run.
if [ ! -x "$PY" ]; then
  python3 -m venv .venv >/dev/null
fi
"$PY" -m pip install -q -r scripts/requirements.txt >/dev/null 2>&1

exec 3>&1 >"$LOG" 2>&1

echo "Step 02 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $("$PY" --version 2>&1) (.venv)"
echo "node:       $(node --version 2>/dev/null || echo 'not installed')"

expect "Step 01 regression: validator" 0 python3 scripts/validate_inputs.py
expect "Step 01 regression: its tests (standard library)" 0 python3 -m unittest discover -s scripts/tests -p 'test_validate_inputs.py'
expect "UC-01..UC-15: full use-case suite" 0 "$PY" -m unittest discover -s scripts/tests -v
expect "Contract checker (all sections)" 0 "$PY" scripts/check_contracts.py
expect "OpenAPI matches the route table" 0 "$PY" scripts/build_openapi.py --check
expect "Fixtures match their generator" 0 "$PY" scripts/build_fixtures.py --check
expect "JavaScript agrees on hashes and offsets" 0 node scripts/jcs_check.mjs

fresh_copy "$T/n1"
edit_json "$T/n1/contracts/v1/journeys.json" "d['journeys'][7]['steps'][1]['actor'] = 'analyst'"
expect_failure "N1: an analyst publishing in a journey must fail" "may not call publish" in_copy "$T/n1" "$PY" scripts/check_contracts.py

fresh_copy "$T/n2"
edit_json "$T/n2/contracts/v1/fixtures/content.json" "next(c for c in d['cases'] if c['name'] == 'content_revision_approved')['instance']['payload']['heading'] = 'Silently edited'"
expect_failure "N2: an approved payload edited without a new hash must fail" "payload_sha256 does not match the payload" in_copy "$T/n2" "$PY" scripts/check_contracts.py

fresh_copy "$T/n3"
edit_json "$T/n3/contracts/v1/agents.schema.json" "d['\$defs']['IdentityResult']['properties']['segments']['items']['properties']['rationale']['minLength'] = 1"
expect_failure "N3: a keyword Claude structured outputs reject must fail" "keyword 'minLength' is not supported" in_copy "$T/n3" "$PY" scripts/check_contracts.py

fresh_copy "$T/n4"
edit_json "$T/n4/contracts/v1/state_machines.json" "m = d['machines']['publication_operation']; m['transitions'] = [t for t in m['transitions'] if t['to'] != 'rolled_back']"
expect_failure "N4: an unreachable status must fail" "'rolled_back' is unreachable" in_copy "$T/n4" "$PY" scripts/check_contracts.py

fresh_copy "$T/n5"
edit_json "$T/n5/contracts/v1/routes.json" "d['routes'][0]['summary'] = 'Changed without regenerating'"
expect_failure "N5: a route change without regenerating OpenAPI must fail" "openapi.json is out of date" in_copy "$T/n5" "$PY" scripts/check_contracts.py

fresh_copy "$T/n6"
edit_json "$T/n6/contracts/v1/fixtures/hashing.json" "d['cases'][0]['sha256'] = 'sha256:' + '0' * 64"
expect_failure "N6: JavaScript must catch a hash that Python got wrong" "sha256 differs from Python" in_copy "$T/n6" node scripts/jcs_check.mjs

expect "Hygiene: no .env, .DS_Store or .venv in git" 0 no_tracked_secrets_or_env
expect "Hygiene: GitHub repo is private, default branch main" 0 repo_is_private_on_main

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
