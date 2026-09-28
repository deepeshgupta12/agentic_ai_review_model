#!/usr/bin/env bash
# Step 04 mutation check: each identity rule below is disabled in a scratch copy of the backend; the test file
# written for it must then fail, and the named test must be among the failures. The real files are never changed.
# Output is saved to logs/step-04/mutation-check-<UTC time>.log. Needs the Compose MongoDB running (`make up`).
#
#   bash scripts/run_step04_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-04
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
  if echo "$out" | grep -qE "^FAILED tests/$file::$must_fail( |$)"; then
    echo "--> OK (caught by $must_fail)"
  else
    echo "--> NOT OK (expected $must_fail to fail)"
    FAILED=1
  fi
}

exec 3>&1 >"$LOG" 2>&1
echo "Step 04 mutation check: each identity rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy imports its own code and the Step 04 test files pass\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
for f in test_identity_matching.py test_identity_links.py test_aliases.py test_identity_agent.py test_projects_api.py test_queries.py; do
  printf '%-28s %s\n' "$f" "$(tests_in $f | tail -1)"
done

mutant "same name in another city is rejected" test_identity_matching.py test_same_name_in_another_city_is_rejected \
  app/identity/matching.py \
  'elif any(c.startswith("other_city") for c in conflicts) and not candidate.own_place:' \
  'elif False:'

mutant "context-required aliases need the developer or locality" test_identity_matching.py test_context_required_alias_needs_developer_or_locality \
  app/identity/matching.py \
  'if alias.mode == "context_required" and not context:' \
  'if False:'

mutant "a phase number followed by BHK is not a phase" test_identity_matching.py test_a_phase_ending_in_a_number_does_not_match_before_bhk \
  app/identity/text.py \
  '    if not phrase_norm.split()[-1].isdigit():' \
  '    if True:'

mutant "several projects in one passage go to review" test_identity_matching.py test_two_projects_in_one_paragraph_both_go_to_review \
  app/identity/matching.py \
  'extra = ["multiple_projects"] if len(named) > 1 else None
            outcomes += [_outcome(i.id, whole, c, extra) for i, c in named]' \
  'outcomes += [_outcome(i.id, whole, c) for i, c in named]'

mutant "auto-accept threshold" test_identity_matching.py test_name_without_place_goes_to_review \
  app/identity/rules.py \
  'AUTO_ACCEPT_SCORE = 550' \
  'AUTO_ACCEPT_SCORE = 400'

mutant "link decisions check the expected version" test_identity_links.py test_accept_with_a_phase_and_version_and_role_checks \
  app/identity/links.py \
  'if link["version"] != body["expected_version"]:' \
  'if False:'

mutant "link decisions follow the state machine" test_identity_links.py test_decisions_follow_the_state_machine_and_the_contract \
  app/identity/links.py \
  'if not contracts.transition_allowed("source_link", link["status"], to_status, actor_role):' \
  'if False:'

mutant "leaving an accepted state invalidates dependants" test_identity_links.py test_moderator_rejects_a_wrong_match_and_dependants_are_invalidated \
  app/identity/links.py \
  '        enqueue_invalidation(db, updated, session)' \
  '        pass'

mutant "a proposal needs a strong identifier in a cited span" test_aliases.py test_valid_model_output_without_a_strong_identifier_is_rejected \
  app/identity/aliases.py \
  'return next((k for k in STRONG_PRIORITY if k in found), None)' \
  'return next((k for k in STRONG_PRIORITY if k in found), "known_project_name")'

mutant "cited evidence must come from the task input" test_aliases.py test_evidence_outside_the_task_or_without_the_alias_is_refused \
  app/identity/aliases.py \
  'if not cited or any(e not in allowed_evidence for e in cited):' \
  'if not cited or all(e not in allowed_evidence for e in cited):'

mutant "generic or colliding names only as context-required" test_aliases.py test_generic_names_can_only_be_approved_as_context_required \
  app/identity/aliases.py \
  'if body["action"] == "approve" and proposal["collision"]["status"] != "none" and mode != "context_required":' \
  'if False:'

mutant "revoking an alias returns its matches to review" test_aliases.py test_revoking_sends_the_matches_it_produced_back_to_review \
  app/identity/aliases.py \
  '            returned = return_to_review(' \
  '            returned = [] or (lambda *a: [])('

mutant "the model cannot change a link status" test_identity_agent.py test_a01_annotates_review_links_but_never_decides \
  app/identity/agent.py \
  'changes: dict[str, Any] = {"match.method": "identity_agent", "match.rationale": rationale}' \
  'changes: dict[str, Any] = {"match.method": "identity_agent", "match.rationale": rationale, "status": "accepted"}'

mutant "rejected names become query exclusions" test_aliases.py test_list_decide_roles_versions_and_reasons \
  app/identity/queries.py \
  'exclusions = list(dict.fromkeys([*config["negative_keywords"], *rejected]))' \
  'exclusions = list(dict.fromkeys(config["negative_keywords"]))'

mutant "an Idempotency-Key reused with another body is refused" test_projects_api.py test_import_needs_an_idempotency_key_and_replays_the_same_result \
  app/api/idempotency.py \
  '        if existing["digest"] != digest:' \
  '        if False:'

mutant "status records name the project's own registrations" test_projects_api.py test_config_changes_need_the_expected_version \
  app/api/routes_projects.py \
  '        if wrong:
            raise ApiError(' \
  '        if False:
            raise ApiError('

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
