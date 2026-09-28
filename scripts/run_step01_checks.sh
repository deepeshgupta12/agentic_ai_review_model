#!/usr/bin/env bash
# Step 01 checks: the automated use-case suite, the validator on the real files,
# five negative checks on temporary copies (real files are never changed) and
# repository hygiene. Output is printed and saved to
# logs/step-01/checks-<UTC time>.log. Exit code 0 only if every check is OK.
#
#   bash scripts/run_step01_checks.sh

set -u
cd "$(dirname "$0")/.."

LOG_DIR=logs/step-01
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checks-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILED=0

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

make_variant() { # make_variant <source json> <dest json> <python statement changing d>
  python3 - "$1" "$2" "$3" <<'EOF'
import json, sys
src, dest, change = sys.argv[1:4]
d = json.load(open(src, encoding="utf-8"))
exec(change)
json.dump(d, open(dest, "w", encoding="utf-8"), ensure_ascii=False)
EOF
}

json_summary() {
  python3 scripts/validate_inputs.py --json | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d["result"], json.dumps(d["summary"]))
sys.exit(0 if d["result"] == "pass" else 1)'
}

no_env_or_ds_store_tracked() {
  local hits
  hits=$(git ls-files | grep -E '(^|/)\.env$|\.DS_Store$')
  if [ -n "$hits" ]; then echo "tracked: $hits"; return 1; fi
  echo "no .env or .DS_Store tracked"
}

repo_is_private_on_main() {
  local value
  value=$(gh repo view --json visibility,defaultBranchRef -q '.visibility + " " + .defaultBranchRef.name') || return 2
  echo "$value"
  [ "$value" = "PRIVATE main" ]
}

exec 3>&1 >"$LOG" 2>&1

echo "Step 01 checks"
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- . ":(exclude)$LOG_DIR" 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD 2>/dev/null || echo unknown)${dirty:+ (plus uncommitted changes)}"
echo "python:     $(python3 --version 2>&1)"

expect "UC-01..UC-07 automated suite" 0 python3 -m unittest discover -s scripts/tests -p 'test_validate_inputs.py' -v
expect "Validator on the repository files" 0 python3 scripts/validate_inputs.py
expect "Validator JSON summary" 0 json_summary

sed 's/"Sector 76"/"<Locality>"/' contracts/five-project-input-template.json > "$T/n1.json"
expect "N1: placeholder in a required field must fail" 1 python3 scripts/validate_inputs.py --projects "$T/n1.json"

make_variant seed/connectors.json "$T/n2.json" "d['connectors'][0]['status'] = 'live'"
expect "N2: connector marked live without a recorded demonstration must fail" 1 python3 scripts/validate_inputs.py --connectors "$T/n2.json"

make_variant seed/source_policies.json "$T/n3.json" "next(p for p in d['policies'] if p['family'] == 'reddit')['ai_processing_allowed'] = True"
expect "N3: AI processing switched on for a blocked source must fail" 1 python3 scripts/validate_inputs.py --policies "$T/n3.json"

make_variant seed/connectors.json "$T/n4.json" "d['connectors'][0]['quota'] = {'api_key': 'sk-ant-FAKEKEYFORTESTING'}"
expect "N4: secret-like value in seed data must fail" 1 python3 scripts/validate_inputs.py --connectors "$T/n4.json"

make_variant contracts/five-project-input-template.json "$T/n5.json" "d['projects'][4] = dict(d['projects'][0], rera_ids=[], client_ref=None)"
expect "N5: duplicate project must fail" 1 python3 scripts/validate_inputs.py --projects "$T/n5.json"

expect "Hygiene: no .env or .DS_Store in git" 0 no_env_or_ds_store_tracked
expect "Hygiene: GitHub repo is private, default branch main" 0 repo_is_private_on_main

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL CHECKS OK"; else echo "SOME CHECKS NOT OK"; fi
echo "log: $LOG"

exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
