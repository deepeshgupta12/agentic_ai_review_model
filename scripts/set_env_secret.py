#!/usr/bin/env python3
"""Put one credential into the local .env from a hidden prompt. The value is never printed or logged.

Only names listed in .env.example are accepted. The file stays git-ignored with permissions 600.
Standard library only.

    python3 scripts/set_env_secret.py ANTHROPIC_API_KEY
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def known_names() -> set[str]:
    names = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return names


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 scripts/set_env_secret.py NAME", file=sys.stderr)
        return 2
    name = argv[0]
    if name not in known_names():
        print(f"{name} is not a setting in .env.example", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("Run this in a terminal, so the value can be read without showing it. .env is unchanged.", file=sys.stderr)
        return 2
    try:
        value = getpass.getpass(f"{name} (typing and pasting stay hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; .env is unchanged.", file=sys.stderr)
        return 1
    if not value:
        print("Nothing entered; .env is unchanged.", file=sys.stderr)
        return 1
    if any(ch in value for ch in "\r\n\0") or value != value.strip("'\""):
        print("The value contains quotes or line breaks; paste the bare key. .env is unchanged.", file=sys.stderr)
        return 1
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [line for line in lines if not line.startswith(f"{name}=")] + [f"{name}={value}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env, 0o600)
    print(f"{name} saved in .env ({len(value)} characters; value not shown).")
    print("Run `make up` so the services pick it up, then `make config` to confirm it is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
