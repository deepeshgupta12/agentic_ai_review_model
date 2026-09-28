#!/usr/bin/env bash
# Step 03 mutation check: each rule below is disabled in a scratch copy of the backend; the
# backend tests must then fail, and the failing tests must be the ones written for that rule.
# The real files are never changed. Output is saved to logs/step-03/mutation-check-<UTC time>.log.
# Needs the Compose MongoDB running (`make up`) and the backend environment (`make install`).
#
#   bash scripts/run_step03_mutations.sh

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG_DIR=logs/step-03
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/mutation-check-$(date -u +%Y%m%dT%H%M%SZ).log"
T=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$T"' EXIT
PYTHON="$ROOT/backend/.venv/bin/python"
FAILED=0

copy_repo() { # the parts the backend tests read: backend, contracts, seed data and contract tools
  rm -rf "$T/repo"
  mkdir -p "$T/repo"
  rsync -a --exclude .venv --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache --exclude __pycache__ \
    "$ROOT/backend" "$ROOT/contracts" "$ROOT/seed" "$ROOT/scripts" "$T/repo/"
}

disable() { # disable <file under backend/> <exact line or fragment> <replacement>
  "$PYTHON" - "$T/repo/backend/$1" "$2" "$3" <<'EOF'
import sys
path, old, new = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"expected exactly one match in {path}, found {text.count(old)}")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
EOF
}

mutant() { # mutant <rule name> <test that must fail> <file> <old> <new>
  local name=$1 must_fail=$2 out
  copy_repo
  printf '\n== rule disabled: %s\n   in backend/%s\n' "$name" "$3"
  if ! disable "$3" "$4" "$5"; then echo "--> NOT OK (could not apply the change)"; FAILED=1; return; fi
  out=$(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -m pytest -q -p no:cacheprovider 2>&1)
  echo "$out" | grep -E '^FAILED ' | sed 's/ - .*//'
  echo "$out" | tail -1
  if echo "$out" | grep -qE "^FAILED tests/[a-z_]+\.py::$must_fail( |$)"; then
    echo "--> OK (caught by $must_fail)"
  else
    echo "--> NOT OK (expected $must_fail to fail)"
    FAILED=1
  fi
}

exec 3>&1 >"$LOG" 2>&1
echo "Step 03 mutation check: each rule is disabled on a scratch copy; its own tests must fail."
echo "date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
dirty=$(git status --porcelain -- backend 2>/dev/null)
echo "commit:     $(git rev-parse --short HEAD)${dirty:+ (plus uncommitted backend changes)}"

copy_repo
printf '\n== baseline: the unchanged copy passes and imports its own code\n'
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -c 'import app, sys; sys.exit(0 if app.__file__.startswith(sys.argv[1]) else 1)' "$T/repo/backend") \
  && echo "imports the scratch copy" || { echo "--> NOT OK (tests would import the real files)"; FAILED=1; }
(cd "$T/repo/backend" && PYTHONPATH="$T/repo/backend" "$PYTHON" -m pytest -q -p no:cacheprovider 2>&1 | tail -1)

mutant "fencing: a stale token may still complete a job" test_expired_worker_cannot_complete_its_successors_job \
  app/jobs/queue.py \
  'return {"_id": job_id, "status": "running", "lease.fencing_token": token}' \
  'return {"_id": job_id, "status": "running"}'

mutant "lease recovery: an expired lease is not returned to the queue" test_claimed_job_survives_a_worker_restart \
  app/jobs/queue.py \
  'expired = {"status": "running", "lease.expires_at": {"$lt": now}}' \
  'expired = {"status": "running", "lease.expires_at": {"$lt": now - timedelta(days=1)}}'

mutant "roles: any signed-in user may call any operation" test_wrong_role_is_forbidden \
  app/api/deps.py \
  'raise ApiError(403, "forbidden", "Your role does not allow this action")' \
  'held = allowed[:1]'

mutant "CSRF: mutations accepted without the token" test_mutation_without_csrf_token_is_rejected \
  app/api/deps.py \
  'if request.method in MUTATING and not csrf_matches(session, request.headers.get(CSRF_HEADER)):' \
  'if False:'

mutant "session signature: a tampered cookie is accepted" test_tampered_cookie_is_rejected \
  app/auth/sessions.py \
  'if not hmac.compare_digest(signature, _sign(token, settings.session_secret.get_secret_value())):' \
  'if False:'

mutant "revocation: a logged-out session still works" test_logout_with_csrf_revokes_the_session \
  app/auth/sessions.py \
  'if session is None or session["revoked_at"] is not None or session["expires_at"] <= utcnow():' \
  'if session is None:'

mutant "rate limit: unlimited login attempts" test_repeated_failures_are_rate_limited \
  app/api/routes_auth.py \
  'if failures >= settings.login_attempts_per_window:' \
  'if False:'

mutant "passwords: short passwords accepted" test_a_short_password_is_refused \
  app/auth/passwords.py \
  'MIN_LENGTH = 12' \
  'MIN_LENGTH = 1'

mutant "gateway: a refusal is parsed as output" test_refusal_is_a_failure_not_parsed \
  app/agents/gateway.py \
  'if result.stop_reason == "refusal":' \
  'if False:'

mutant "gateway: repair is not bounded to one attempt" test_second_invalid_output_fails_without_a_third_try \
  app/agents/gateway.py \
  'for repair_round in range(2):' \
  'for repair_round in range(3):'

mutant "logs: redaction switched off" test_redaction_masks_known_secret_shapes_and_registered_values \
  app/observability.py \
  'def redact(text: str) -> str:' \
  'def redact(text: str) -> str:
    return text'

mutant "settings: a failed start echoes configured values" test_a_failed_start_does_not_echo_configured_values \
  app/config.py \
  'hide_input_in_errors=True,' \
  'hide_input_in_errors=False,'

echo
if [ "$FAILED" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; else echo "SOME MUTANTS NOT CAUGHT"; fi
echo "log: $LOG"
exec 1>&3 2>&1
cat "$LOG"
exit "$FAILED"
