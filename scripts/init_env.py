#!/usr/bin/env python3
"""Create or complete .env from .env.example without overwriting existing values.

Adds missing keys and generates SESSION_SECRET and REVALIDATION_SECRET when empty.
Prints key names only, never values. Standard library only.

    python3 scripts/init_env.py
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ("SESSION_SECRET", "REVALIDATION_SECRET")


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    example, env = ROOT / ".env.example", ROOT / ".env"
    current = parse(env)
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    added, generated = [], []
    for key, default in parse(example).items():
        if key in GENERATED and not current.get(key):
            value = secrets.token_urlsafe(48)
            generated.append(key)
        elif key in current:
            continue
        else:
            value = default
            added.append(key)
        lines = [line for line in lines if not line.startswith(f"{key}=")]
        lines.append(f"{key}={value}")
        current[key] = value
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env, 0o600)
    print(f".env ready: added {len(added)} keys; generated {', '.join(generated) or 'no secrets (already set)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
