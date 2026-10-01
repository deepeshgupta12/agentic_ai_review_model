#!/usr/bin/env bash
# Step 06 mutation check: each media rule below is disabled in a scratch copy of the backend; the test file
# written for it must then fail, and the named test must be among the failures. The real files are never changed.
# Output is saved to logs/step-06/mutation-check-<UTC time>.log. Needs the Compose MongoDB running (`make up`).
#
#   bash scripts/run_step06_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-06
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
echo "Step 06 mutation check: each media rule is disabled on a scratch copy; its own test must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy imports its own code and the Step 06 test file passes\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
printf '%-28s %s\n' test_media.py "$(tests_in test_media.py | tail -1)"

mutant "only videos with an accepted match are processed" test_media.py test_only_videos_with_an_accepted_match_are_queued_once \
  app/media/pipeline.py \
  'query: dict[str, Any] = {"status": {"$in": sorted(ACTIVE_STATUSES)}, "segment_key": "whole"}' \
  'query: dict[str, Any] = {"segment_key": "whole"}'

mutant "captions come before audio" test_media.py test_captions_come_first_and_become_segments_on_the_original_timeline \
  app/media/pipeline.py \
  '        if track is not None and track.cues:' \
  '        if False:'

mutant "a refusal stops the attempt and is recorded" test_media.py test_a_refusal_is_recorded_not_worked_around \
  app/media/pipeline.py \
  '    except (MediaRefused, MediaUnavailable) as exc:' \
  '    except MediaUnavailable as exc:'

mutant "a long video without captions is not downloaded" test_media.py test_a_long_video_without_captions_is_not_downloaded \
  app/media/pipeline.py \
  'if duration is None or duration > settings.media_max_duration_seconds * 1000:' \
  'if duration is None:'

mutant "the audio is deleted after transcription" test_media.py test_without_captions_the_audio_is_transcribed_locally_and_then_deleted \
  app/media/pipeline.py \
  '                shutil.rmtree(workdir, ignore_errors=True)  # the audio is never kept' \
  '                pass'

mutant "media states follow the contract" test_media.py test_media_state_changes_follow_the_contract \
  app/media/pipeline.py \
  '    if not contracts.transition_allowed("media_access", current, to, "system"):' \
  '    if False:'

mutant "windows never overlap" test_media.py test_a_long_pause_closes_a_window_and_overlapping_captions_are_clipped \
  app/media/windows.py \
  '            end = min(end, groups[i + 1][0].start_ms)' \
  '            pass'

mutant "a window naming a project does not also inherit" test_media.py test_windows_inherit_the_videos_match_and_a_named_project_gets_its_own \
  app/identity/service.py \
  '            if segment["segment_key"] in named_keys:' \
  '            if False:'

mutant "speech evidence is governed by the spoken-content policy" test_media.py test_windows_inherit_the_videos_match_and_a_named_project_gets_its_own \
  app/identity/evidence.py \
  '        "policy": policy_ref,' \
  '        "policy": source["policy"],'

mutant "inherited windows return to review with the video's match" test_media.py test_undoing_the_videos_match_sends_inherited_windows_back_to_review \
  app/identity/links.py \
  '    if link["segment_key"] == "whole":' \
  '    if False:'

mutant "withdrawing a video erases its transcript" test_media.py test_withdrawing_a_video_erases_its_transcript \
  app/sources/lifecycle.py \
  '        if segment_refs:' \
  '        if False:'

mutant "machine-made numbers are flagged" test_media.py test_flags_mark_code_switching_numbers_music_and_low_confidence \
  app/media/language.py \
  '    if NUMBER.search(window.text) and (low or machine):' \
  '    if NUMBER.search(window.text) and low:'

mutant "a translation must keep every number" test_media.py test_a04_translations_are_kept_only_when_numbers_and_negations_survive \
  app/media/translate.py \
  '    missing = numbers(original) - numbers(text)' \
  '    missing: set[str] = set()'

mutant "Hindi negation markers need Devanagari word edges" test_media.py test_negation_markers_respect_devanagari_word_edges \
  app/media/translate.py \
  '_NOT_DEVA_BEFORE, _NOT_DEVA_AFTER = r"(?<![\u0900-\u097F])", r"(?![\u0900-\u097F])"' \
  '_NOT_DEVA_BEFORE, _NOT_DEVA_AFTER = "", ""'

mutant "the general worker never takes media jobs" test_media.py test_the_media_worker_takes_only_media_jobs \
  app/workers/worker.py \
  '        return [kind for kind in queue.JOB_KINDS if kind not in MEDIA_KINDS]' \
  '        return list(queue.JOB_KINDS)'

mutant "the verifier rejects speech evidence under another policy" test_media.py test_the_collection_checks_accept_transcripts_and_catch_broken_ones \
  app/sources/verify.py \
  'broken = [e["_id"] for e in speech if e["policy"]["family"] != "spoken_video_content"]' \
  'broken = []'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
