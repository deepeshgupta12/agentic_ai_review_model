#!/usr/bin/env bash
# Steps 09-10 mutation check: each console, content, approval, publication and caching rule below is disabled in a scratch
# copy of the backend; the test file written for it must then fail, and the named test must be among the failures. The
# real files are never changed. Output is saved to logs/step-09/mutation-check-<UTC time>.log. Needs the Compose
# MongoDB running (`make up`). No model call is made.
#
#   bash scripts/run_step09_10_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-09
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/mutation-check-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$T"' EXIT
PYTHON="$ROOT/backend/.venv/bin/python"
FAILED=0

copy_repo() { # what the backend tests read: backend, contracts, seed, scripts, prompts and evals
  rm -rf "$T/repo"
  mkdir -p "$T/repo"
  rsync -a --exclude .venv --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache --exclude __pycache__ \
    "$ROOT/backend" "$ROOT/contracts" "$ROOT/seed" "$ROOT/scripts" "$ROOT/prompts" "$ROOT/evals" "$T/repo/"
}

disable() { # disable <file under backend/> <exact text> <replacement>
  "$PYTHON" - "$T/repo/backend/$1" "$2" "$3" <<'EOF'
import sys
path, old, new = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"expected exactly one match in {path}, found {text.count(old)}")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
EOF
}

tests_in() { # tests_in <test file>: run one test file in the scratch copy
  (cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -m pytest -q -p no:cacheprovider "tests/$1" 2>&1)
}

mutant() { # mutant <rule> <test file> <test that must fail> <file> <old> <new>
  local name=$1 file=$2 must_fail=$3 out
  copy_repo
  printf '\n== rule disabled: %s\n   in backend/%s\n' "$name" "$4"
  if ! disable "$4" "$5" "$6"; then echo "--> NOT OK (could not apply the change)"; FAILED=1; return; fi
  out=$(tests_in "$file")
  echo "$out" | grep -E '^FAILED ' | sed 's/ - .*//'
  echo "$out" | tail -1
  if echo "$out" | grep -qE "^FAILED tests/$file::$must_fail( |\[|$)"; then
    echo "--> OK (caught by $must_fail)"
  else
    echo "--> NOT OK (expected $must_fail to fail)"
    FAILED=1
  fi
}

exec 3>&1 >"$LOG" 2>&1
echo "Steps 09-10 mutation check: each rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"

mutant "final approval binds the exact payload and manifest hashes" test_content.py test_final_approval_binds_hash_epoch_and_state_version \
  app/content/service.py \
  '        if body["payload_sha256"] != payload_sha or body["manifest_sha256"] != manifest_sha:' \
  '        if False:'

mutant "final approval binds the evidence epoch" test_content.py test_final_approval_binds_hash_epoch_and_state_version \
  app/content/service.py \
  '        if body["eligibility_epoch"] != state["eligibility_epoch"]:' \
  '        if False:'

mutant "a page from reviews alone calls no model (D64)" test_content.py test_a_page_from_reviews_alone_needs_no_model \
  app/content/service.py \
  $'    if findings:\n        written = editor.write_draft(' \
  $'    if True:\n        written = editor.write_draft('

mutant "an opinion written as a universal fact blocks approval" test_content.py test_qa_blocks_opinion_as_fact_new_numbers_lost_caveats_occupancy_and_changed_reviews \
  app/content/qa.py \
  '        if all(f["attribution"] == "reported_opinion" for f in cited) and not cues.search(text):' \
  '        if False:'

mutant "a shown review must equal its approved record (D28)" test_content.py test_qa_blocks_opinion_as_fact_new_numbers_lost_caveats_occupancy_and_changed_reviews \
  app/content/qa.py \
  '        elif review != expected:' \
  '        elif False:'

mutant "delivery is verified from the rendered page's markers" test_content.py test_a_page_showing_the_wrong_revision_is_never_reported_as_delivered \
  app/publication/service.py \
  '    verified = markers.get("state") == expected_state and (' \
  '    verified = True or ('

mutant "withdrawn evidence disables serving at once" test_content.py test_withdrawn_evidence_stops_serving_and_cannot_be_rolled_back_to \
  app/publication/service.py \
  '            changes["serving_state"] = "temporarily_disabled"' \
  '            pass'

mutant "a finding edit cannot relabel an opinion as a verified fact" test_console_api.py test_a_finding_edit_is_a_new_revision_that_keeps_the_evidence_rules \
  app/workflows/revisions.py \
  '        if body["attribution"] != expected:' \
  '        if False:'

mutant "public corrections are rate-limited per address" test_console_api.py test_public_corrections_are_rate_limited_and_moderated \
  app/api/routes_corrections.py \
  '    if db["login_attempts"].count_documents({"key": key, "at": {"$gte": since}}) >= settings.corrections_per_hour:' \
  '    if False:'

mutant "an admin cannot lock themselves out" test_console_api.py test_users_and_roles_are_admin_only_and_an_admin_cannot_lock_themselves_out \
  app/api/routes_admin.py \
  '    if user_id == principal.user_id:' \
  '    if False:'

mutant "adding a project from the console never updates an existing one (D58)" test_console_api.py test_a_researcher_adds_one_project_from_the_console \
  app/api/routes_projects.py \
  '        if db["projects"].find_one({"match_key": match_key(item["project_name"], item["city"])}, {"_id": 1}):' \
  '        if False:'

mutant "prompt caching marks the shared instructions (D65)" test_gateway.py test_the_shared_instructions_carry_the_only_cache_breakpoint \
  app/agents/gateway.py \
  '    return [{"type": "text", "text": system, "cache_control": control}], tokens' \
  '    return system, 0'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
