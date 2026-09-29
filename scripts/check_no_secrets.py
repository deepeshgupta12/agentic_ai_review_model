#!/usr/bin/env python3
"""Stop credentials from reaching git. Prints setting names only, never values. Standard library only.

    python3 scripts/check_no_secrets.py --staged    what is about to be committed (the pre-commit hook)
    python3 scripts/check_no_secrets.py --tracked   every tracked file
    python3 scripts/check_no_secrets.py --example   only .env.example (used in CI, where no .env exists)

Always checks that the secret settings in .env.example are empty. With a local .env, also checks that none of
its secret values appears in the staged changes or tracked files. Exit code 1 when something is found.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Settings in .env.example that are configuration, not credentials.
NOT_SECRET = {
    "APP_MODE", "LOG_LEVEL", "MONGODB_URI", "MONGODB_DB", "COOKIE_SECURE", "WEB_ORIGIN", "PUBLIC_BASE_URL",
    "MODEL_ROUTINE", "MODEL_REASONING", "MODEL_DIFFICULT",
}  # fmt: skip
MIN_LENGTH = 8  # shorter values are too common to search for


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


def filled_example_secrets() -> list[str]:
    return [k for k, v in read_env(ROOT / ".env.example").items() if k not in NOT_SECRET and v]


def secrets_from_env() -> dict[str, str]:
    return {k: v for k, v in read_env(ROOT / ".env").items() if k not in NOT_SECRET and len(v) >= MIN_LENGTH}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "--staged"
    if mode not in ("--staged", "--tracked", "--example"):
        print(__doc__)
        return 2
    problems = [f".env.example: {name} has a value; it must stay empty" for name in filled_example_secrets()]
    secrets = {} if mode == "--example" else secrets_from_env()
    if secrets:
        if mode == "--staged":
            added = "\n".join(
                line[1:] for line in git("diff", "--cached", "-U0", "--no-color").splitlines() if line.startswith("+")
            )
            problems += [f"staged changes contain the value of {name}" for name, value in secrets.items() if value in added]
        else:
            for name, value in secrets.items():
                hits = subprocess.run(["git", "grep", "-lF", "--", value], cwd=ROOT, capture_output=True, text=True)
                problems += [f"{path}: contains the value of {name}" for path in hits.stdout.split()]
    if problems:
        print("Secret check FAILED (values not shown):")
        for problem in problems:
            print(f"  - {problem}")
        print("Keep credentials only in .env (git-ignored). Unstage with `git restore --staged <file>`.")
        return 1
    checked = "no .env; .env.example only" if not secrets and mode != "--example" else f"{len(secrets)} secret values"
    print(f"Secret check OK ({mode[2:]}; {checked if mode != '--example' else '.env.example'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
