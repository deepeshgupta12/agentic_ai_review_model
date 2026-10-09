#!/usr/bin/env bash
# Step 07 mutation check: each evidence rule below is disabled in a scratch copy of the backend; the test file
# written for it must then fail, and the named test must be among the failures. The real files are never changed.
# Output is saved to logs/step-07/mutation-check-<UTC time>.log. Needs the Compose MongoDB running (`make up`).
#
#   bash scripts/run_step07_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-07
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
echo "Step 07 mutation check: each evidence rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy imports its own code and the Step 07 test file passes\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
printf '%-28s %s\n' test_evidence.py "$(tests_in test_evidence.py | tail -1)"

mutant "a temporarily unavailable source is not used" test_evidence.py test_one_eligibility_rule_serves_support_identity_and_the_api \
  app/evidence/eligibility.py \
  '    "unavailable": "source_unavailable",' \
  ''

mutant "a link of another project never supports this one" test_evidence.py test_one_eligibility_rule_serves_support_identity_and_the_api \
  app/evidence/eligibility.py \
  '    if link is None or link["status"] not in allowed or link["project_id"] != evidence["project_id"]:' \
  '    if link is None or link["status"] not in allowed:'

mutant "the retrieval filter admits only usable source revisions" test_evidence.py test_the_retrieval_filter_admits_exactly_what_the_rule_admits \
  app/evidence/eligibility.py \
  '"lifecycle": {"$in": list(USABLE_SOURCE_LIFECYCLES)}' \
  '"lifecycle": {"$exists": True}'

mutant "erasure removes the search copy of the words" test_evidence.py test_withdrawn_or_unaccepted_evidence_leaves_retrieval_at_once_and_its_words_leave_the_index \
  app/sources/lifecycle.py \
  '        retrieval.remove_source(db, source["id"], source["revision"], session=session)  # the search copy too' \
  '        pass'

mutant "the text index does not read evidence language as a stemming language" test_evidence.py test_search_ranks_this_projects_words_and_never_another_projects \
  app/setup/database.py \
  '{"default_language": "none", "language_override": "search_language_override"}' \
  '{"default_language": "none"}'

mutant "lineage matches exact revisions" test_evidence.py test_lineage_follows_exact_revisions_from_source_to_content \
  app/evidence/lineage.py \
  '        if _cites(c["supporting_evidence"] + c["contradicting_evidence"], evidence_pairs)' \
  '        if True'

mutant "approvals resting on ineligible evidence are withdrawn" test_evidence.py test_a_source_correction_reaches_every_draft_and_active_revision_and_withdraws_approvals \
  app/identity/invalidation.py \
  '            if current not in WITHDRAWABLE or not contracts.transition_allowed(' \
  '            if True or not contracts.transition_allowed('

mutant "the invalidation follows evidence that became ineligible" test_evidence.py test_a_source_correction_reaches_every_draft_and_active_revision_and_withdraws_approvals \
  app/identity/invalidation.py \
  '    ineligible = [e for e in evidence if not eligibility(db, e).eligible]' \
  '    ineligible: list[dict[str, Any]] = []'

mutant "anchors are re-derived from the source text" test_evidence.py test_anchor_checks_rederive_every_excerpt \
  app/evidence/anchors.py \
  '            elif text[anchor["start"] : anchor["end"]] != excerpt:' \
  '            elif False:'

mutant "text evidence is stored with its context" test_evidence.py test_evidence_is_stored_with_its_context \
  app/identity/evidence.py \
  '        "context_anchor": text_context(text, start, end),' \
  '        "context_anchor": None,'

mutant "clustering is queued only when evidence waits" test_evidence.py test_new_evidence_is_clustered_by_a_scheduled_job_within_the_hour \
  app/evidence/clusters.py \
  '    if not db["ai_evidence"].count_documents({"origin_cluster": None, "excerpt_text": {"$type": "string"}}, limit=1):' \
  '    if False:'

mutant "short identical comments stay separate opinions" test_evidence.py test_short_identical_comments_stay_separate_opinions \
  app/evidence/clusters.py \
  '    sets = {k: shingles(t) for k, t in texts.items() if t and len(words(t)) >= MIN_WORDS}' \
  '    sets = {k: shingles(t) for k, t in texts.items() if t}'

printf '\n-- embedding search (D51)\n'

mutant "hybrid ranking fuses vectors with keywords" test_evidence.py test_vectors_find_what_keywords_miss_and_hybrid_keeps_both \
  app/evidence/retrieval.py \
  '    if mode == "keyword" or not similar:' \
  '    if True:'

mutant "a down embedder falls back to keywords" test_evidence.py test_without_the_embedder_search_falls_back_to_keywords_and_says_so \
  app/evidence/retrieval.py \
  '                degraded = f"embedder unavailable ({exc}): keyword ranking only"' \
  '                raise'

mutant "a new model means new vectors" test_evidence.py test_vectors_are_made_by_a_scheduled_job_and_remade_for_a_new_model \
  app/embeddings/jobs.py \
  '    return {"$or": [{"embedding": None}, {"embedding_model": {"$ne": model_label(settings)}}]}' \
  '    return {"embedding": None}'

mutant "entries whose evidence lost its words leave the index" test_evidence.py test_vectors_are_made_by_a_scheduled_job_and_remade_for_a_new_model \
  app/evidence/retrieval.py \
  '    if stale:' \
  '    if False:'

mutant "a model file must match its pinned hash" test_evidence.py test_a_model_file_that_does_not_match_its_pinned_hash_is_refused \
  app/embeddings/model.py \
  '        if actual != expected:' \
  '        if False:'

printf '\n-- one heavy model at a time in the 4 GB VM (D52)\n'

mutant "embedding waits while transcription is running or waiting" test_evidence.py test_transcription_and_embedding_take_turns_in_the_4_gb_vm \
  app/embeddings/jobs.py \
  '        raise Deferred("transcription is running or waiting; it goes first in the 4 GB VM (D52)", 300)' \
  '        pass'

mutant "transcription waits while the embedder is working" test_evidence.py test_transcription_and_embedding_take_turns_in_the_4_gb_vm \
  app/media/pipeline.py \
  '        raise Deferred("the embedder is working; Whisper waits for the memory (4 GB VM, D52)", 30)' \
  '        pass'

mutant "embedding steps aside between texts for transcription" test_evidence.py test_transcription_and_embedding_take_turns_in_the_4_gb_vm \
  app/embeddings/jobs.py \
  '        if should_yield():' \
  '        if False:'

mutant "a deferred job keeps its attempts" test_evidence.py test_transcription_and_embedding_take_turns_in_the_4_gb_vm \
  app/workers/worker.py \
  '        return queue.defer(db, claimed.id, claimed.token, exc.reason, exc.seconds)' \
  '        return queue.fail(db, claimed.id, claimed.token, "deferred", exc.reason, retryable=True)'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
