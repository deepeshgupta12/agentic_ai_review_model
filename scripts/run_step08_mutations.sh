#!/usr/bin/env bash
# Step 08 mutation check: each agent, workflow, decision, spend and Instagram rule below is disabled in a scratch copy
# of the backend; the test file written for it must then fail, and the named test must be among the failures. The
# real files are never changed. Output is saved to logs/step-08/mutation-check-<UTC time>.log. Needs the Compose
# MongoDB running (`make up`). No model call is made.
#
#   bash scripts/run_step08_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-08
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
echo "Step 08 mutation check: each rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy imports its own code and the Step 08 test files pass\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
for f in test_agents.py test_workflow.py test_instagram.py test_gateway.py; do
  printf '%-22s %s\n' "$f" "$(tests_in "$f" | tail -1)"
done

printf '\n-- agents: what the backend checks whatever the model writes\n'

mutant "a handle the task did not give is an invented reference" test_agents.py test_a05_sees_handles_not_ids_and_the_backend_drops_invented_or_unsupported_claims \
  app/agents/common.py \
  '            (known if h in self.items else invented).append(self.items.get(h, h))' \
  '            known.append(self.items.get(h, h))'

mutant "a claim may not state a number its evidence does not" test_agents.py test_untrusted_text_cannot_change_the_task \
  app/agents/claims.py \
  '        missing = numbers_in(statement) - numbers_in(sources_text)' \
  '        missing = set()'

mutant "only a cited primary record verifies or contradicts a fact" test_agents.py test_a06_accepts_verified_only_with_a_supplied_primary_record_and_posts_never_contradict \
  app/agents/verify.py \
  '        if status in ("verified", "contradicted") and not records:' \
  '        if False:'

mutant "a flagged claim never reaches a finding (D27)" test_agents.py test_a07_gets_only_usable_claims_with_whole_aspects_packed \
  app/agents/findings.py \
  '        elif claim["consistency_flags"]:' \
  '        elif False:'

mutant "the backend sets a finding's attribution" test_agents.py test_a07_backend_rules_hold_whatever_the_model_writes \
  app/agents/findings.py \
  '        attribution = attribution_for(claims, len(origins))' \
  '        attribution = item.get("attribution") or "reported_opinion"'

mutant "a pro or con must match its claims' polarity" test_agents.py test_a07_backend_rules_hold_whatever_the_model_writes \
  app/agents/findings.py \
  '        if (kind == "pro" and not positive) or (kind == "con" and not negative):' \
  '        if False:'

mutant "a pro resting on a negative claim becomes neutral (conflict stays visible)" test_agents.py test_conflicting_claims_stay_visible_and_no_balance_is_forced \
  app/agents/findings.py \
  '                kind, fixes["kind_set_neutral"] = "neutral", fixes["kind_set_neutral"] + 1' \
  '                fixes["kind_set_neutral"] += 1'

mutant "a verbatim review equals the original words" test_agents.py test_rendering_checks_compare_every_word_with_the_original \
  app/agents/reviews.py \
  '        return None if _spaced(text) == _spaced(original) else "verbatim_changed"' \
  '        return None'

mutant "a review never mixes two people's sources" test_agents.py test_a11_reviews_come_from_one_source_in_the_authors_own_words \
  app/agents/reviews.py \
  '        if not cited or any(e["id"] not in own for e in cited):' \
  '        if not cited:'

mutant "a review with a phone number or e-mail address is dropped" test_agents.py test_a_resident_review_before_possession_is_flagged_and_personal_data_is_never_shown \
  app/agents/reviews.py \
  '        if PHONE.search(text) or EMAIL.search(text):' \
  '        if False:'

printf '\n-- decisions and the workflow\n'

mutant "a decision names the latest revision" test_workflow.py test_decisions_name_the_exact_revision_and_come_from_a_moderator_session \
  app/workflows/decisions.py \
  '        if latest["revision"] != body["revision"]:' \
  '        if False:'

mutant "an approval re-checks flags and eligibility" test_workflow.py test_decisions_name_the_exact_revision_and_come_from_a_moderator_session \
  app/workflows/decisions.py \
  '        if to == "approved":' \
  '        if False:'

mutant "only a moderator continues an analysis after review" test_workflow.py test_only_a_checked_moderator_selection_resumes_the_graph \
  app/workflows/analysis.py \
  '    if actor.get("kind") != "user" or actor.get("role") != "moderator":' \
  '    if False:'

mutant "the resume job checks the selection again" test_workflow.py test_a_selection_that_changed_after_the_request_is_refused_and_the_graph_stays_paused \
  app/workflows/analysis.py \
  '    if problems:
        raise queue.JobFailure("ineligible_dependency", "; ".join(problems)[:500], retryable=False)' \
  '    if False:
        raise queue.JobFailure("ineligible_dependency", "; ".join(problems)[:500], retryable=False)'

mutant "a pause the worker did not record is recovered" test_workflow.py test_a_crash_at_any_node_recovers_without_duplicates_or_paying_twice \
  app/workflows/analysis.py \
  '    if run is None or run["stage"] not in ("analysing", "findings_review"):' \
  '    if run is None or run["stage"] != "analysing":'

mutant "a finished task's output is reused, never paid for twice" test_workflow.py test_a_crash_at_any_node_recovers_without_duplicates_or_paying_twice \
  app/agents/common.py \
  '    return doc["data"] if doc else None' \
  '    return None'

mutant "an exhausted budget stops the analysis visibly" test_workflow.py test_budget_exhaustion_stops_the_analysis_visibly_and_a_new_budget_continues_it \
  app/workflows/analysis.py \
  'STOP_CODES = {"budget_exhausted", "access_pending",' \
  'STOP_CODES = {"access_pending",'

printf '\n-- spend and Instagram\n'

mutant "a call that could exceed the budget is refused before it is made" test_gateway.py test_a_call_that_could_exceed_the_budget_is_refused_before_it_is_made \
  app/agents/spend.py \
  '                "$expr": {"$lte": [{"$add": ["$spent_usd", "$reserved_usd", amount_usd]}, "$limit_usd"]},' \
  ''

mutant "Scrapfly credits are reserved before the request" test_instagram.py test_a_refused_key_and_spent_credits_stop_the_connector \
  app/connectors/scrapfly.py \
  '        if not quota.reserve(self.db, self.settings, LEDGER, "credits", cost, self.now()):' \
  '        if False:'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
