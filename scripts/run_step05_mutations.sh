#!/usr/bin/env bash
# Step 05 mutation check: each collection rule below is disabled in a scratch copy of the backend; the test file
# written for it must then fail, and the named test must be among the failures. The real files are never changed.
# Output is saved to logs/step-05/mutation-check-<UTC time>.log. Needs the Compose MongoDB running (`make up`).
#
#   bash scripts/run_step05_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-05
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
echo "Step 05 mutation check: each collection rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy imports its own code and the Step 05 test files pass\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
for f in test_policies.py test_fetching.py test_connectors.py test_collection.py test_lifecycle.py test_recheck.py test_runs_api.py; do
  printf '%-28s %s\n' "$f" "$(tests_in $f | tail -1)"
done

mutant "a host's policy is checked before any request" test_connectors.py test_the_web_reader_never_requests_a_page_the_policy_does_not_allow \
  app/connectors/web.py \
  '        if refusal:' \
  '        if False:'

mutant "robots.txt is obeyed where the policy says obey" test_connectors.py test_robots_refusal_and_http_outcomes \
  app/connectors/web.py \
  '        if not decision.allowed and policies.obeys_robots(resolution.policy):' \
  '        if False:'

mutant "record_only logs robots.txt without blocking (D46)" test_connectors.py test_under_record_only_robots_txt_is_logged_but_does_not_block \
  app/sources/policies.py \
  '    return (policy or {}).get("robots_txt", "obey") == "obey"' \
  '    return True'

mutant "a source withdrawn on request is never collected again (D46)" test_lifecycle.py test_a_source_withdrawn_on_request_is_never_collected_again \
  app/sources/store.py \
  'if latest is not None and latest["lifecycle"] == "withdrawn" and withdrawn_on_request(db, latest["id"], session):' \
  'if False:'

mutant "every redirect hop is checked against the policy" test_connectors.py test_a_redirect_to_a_host_the_policy_does_not_allow_is_stopped \
  app/connectors/web.py \
  '            if hop_refusal:' \
  '            if False:'

mutant "the fetch log keeps where a redirect landed" test_connectors.py test_an_allowed_redirect_is_stored_where_it_landed_and_logged_with_both_addresses \
  app/connectors/web.py \
  '            entry["final_url"] = final_url' \
  '            pass'

mutant "dates only from structured markup (D44)" test_connectors.py test_a_date_written_only_in_the_text_stays_unknown \
  app/connectors/web.py \
  'DATE_PARAMS = {"extensive_search": False, "original_date": True}' \
  'DATE_PARAMS = {"extensive_search": True, "original_date": True}'

mutant "non-public addresses are refused (SSRF)" test_fetching.py test_non_public_targets_and_odd_urls_are_refused \
  app/sources/http.py \
  '        if not addresses or not all(public_address(a) for a in addresses):' \
  '        if not addresses:'

mutant "a robots.txt that refuses us means nothing is fetched (D45)" test_fetching.py test_a_robots_file_that_refuses_us_means_nothing_is_fetched \
  app/sources/robots.py \
  '        if response.status in (404, 410):' \
  '        if 400 <= response.status < 500:'

mutant "withdrawal erases older revisions too (D45)" test_lifecycle.py test_withdrawing_a_source_erases_every_revision \
  app/sources/lifecycle.py \
  'if s["lifecycle"] not in ("withdrawn", "deleted", "expired")' \
  'if s["lifecycle"] not in ("withdrawn", "superseded", "deleted", "expired")'

mutant "a confirmed deletion reaches older revisions (D45)" test_lifecycle.py test_a_confirmed_deletion_reaches_older_revisions \
  app/sources/lifecycle.py \
  'for older in db["ai_sources"].find({"id": current["id"], "lifecycle": "superseded"}, session=session):' \
  'for older in []:'

mutant "a search hit found under another title is the same record (D43)" test_fetching.py test_a_search_hit_found_again_under_another_title_is_the_same_record \
  app/sources/store.py \
  'latest["title"] == item.title or item.source_kind == "search_result"' \
  'latest["title"] == item.title'

mutant "no Brave request without a quota reservation" test_connectors.py test_brave_refusal_and_quota_are_explicit \
  app/connectors/brave.py \
  '        if not quota.reserve(self.db, self.settings, self.id, "requests", 1, self.now()):' \
  '        if False:'

mutant "a generic web host must be on the allow-list" test_policies.py test_a_generic_web_host_needs_the_allow_list \
  app/sources/policies.py \
  '    if not _matches(host, web["hosts"]):' \
  '    if False:'

mutant "metadata-only items carry no text" test_fetching.py test_metadata_only_items_carry_no_payload \
  app/sources/store.py \
  '    if metadata_only == (item.text is not None):' \
  '    if False:'

mutant "an unchanged page makes no new revision" test_fetching.py test_storing_the_same_page_again_makes_no_new_revision \
  app/sources/store.py \
  '        if same:' \
  '        if False:'

mutant "a run uses only the connectors it planned (D43)" test_collection.py test_a_connector_the_run_did_not_plan_is_never_called \
  app/sources/collection.py \
  'return build(connector_id, self.db, self.settings) if connector_id in self.planned else None' \
  'return build(connector_id, self.db, self.settings)'

mutant "coverage is partial only when a page may read next time" test_collection.py test_only_a_page_that_may_read_next_time_leaves_coverage_partial \
  app/sources/collection.py \
  '            if outcomes.get("error_will_retry"):' \
  '            if outcomes.get("gone") or outcomes.get("error_will_retry"):'

mutant "inherited comment links return to review with their parent (D42)" test_collection.py test_comments_inherit_their_thread_and_follow_it_back_to_review \
  app/identity/links.py \
  '        _return_inherited(db, contracts, updated, session)' \
  '        pass'

mutant "deletion needs two consecutive 'gone' results" test_lifecycle.py test_deletion_needs_two_consecutive_gone_checks \
  app/sources/lifecycle.py \
  '            if (doc or {}).get("gone", 1) >= 2:' \
  '            if (doc or {}).get("gone", 1) >= 1:'

mutant "erasure waits for dependency invalidation" test_lifecycle.py test_erasure_waits_for_invalidation_then_removes_the_text \
  app/sources/lifecycle.py \
  '    if pending:
        raise NotReady(' \
  '    if False:
        raise NotReady('

mutant "a re-check stores an edited page as a new revision (D44)" test_recheck.py test_an_edited_page_becomes_a_new_revision_linked_to_the_same_project \
  app/sources/recheck.py \
  '        if result.state == "changed" and _store_revision(client, db, contracts, source, result.item):' \
  '        if False:'

mutant "a re-check corrects a stated date the markup does not support (D44)" test_recheck.py test_a_stated_date_the_markup_does_not_support_is_corrected_with_an_audit_event \
  app/sources/recheck.py \
  '            counts["dates_corrected"] += int(_correct_date(client, db, source, result.item))' \
  '            counts["dates_corrected"] += 0'

mutant "verify-collection catches evidence from metadata-only records" test_collection.py test_the_collection_checks_pass_on_a_run_and_catch_planted_violations \
  app/sources/verify.py \
  'if f"{e['"'"'source'"'"']['"'"'id'"'"']}@{e['"'"'source'"'"']['"'"'revision'"'"']}" in metadata_ids' \
  'if False'

mutant "a run needs an Idempotency-Key" test_runs_api.py test_start_run_needs_a_key_a_researcher_and_replays \
  app/api/idempotency.py \
  '    if key is None or not 8 <= len(key) <= 128:' \
  '    if key is not None and not 8 <= len(key) <= 128:'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
