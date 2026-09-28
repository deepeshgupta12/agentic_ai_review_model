"""Seed users from seed/operating_defaults.json `seeded_users` (I09).

Passwords never live in the repository: they come from SEED_USER_PASSWORD (local
.env, git-ignored) or an interactive prompt, must meet the 12-character rule and
are stored only as argon2id hashes. Re-running updates names and roles; an existing
password is changed only with reset_password=True.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pymongo.database import Database

from app import audit
from app.auth.passwords import check_policy, hash_password
from app.db import utcnow
from app.ids import new_id


def seeded_users(seed_dir: Path) -> list[dict[str, Any]]:
    item = json.loads((seed_dir / "operating_defaults.json").read_text(encoding="utf-8"))["items"]["seeded_users"]
    if item["status"] != "accepted" or not item["value"]:
        raise ValueError("no accepted seeded users in seed/operating_defaults.json (I09)")
    return list(item["value"])


def seed_users(
    db: Database[dict[str, Any]], users: list[dict[str, Any]], password: str | None, *, reset_password: bool = False
) -> list[dict[str, Any]]:
    if password is not None:
        check_policy(password)
    report = []
    for spec in users:
        email = spec["email"].strip().lower()
        now = utcnow()
        existing = db["users"].find_one({"email": email})
        if existing is None:
            if password is None:
                raise ValueError(f"a password is needed to create {email}")
            user_id = new_id("usr")
            db["users"].insert_one(
                {
                    "_id": user_id,
                    "email": email,
                    "display_name": spec["display_name"],
                    "roles": spec["roles"],
                    "active": True,
                    "password_hash": hash_password(password),
                    "created_at": now,
                    "updated_at": now,
                }
            )
            outcome = "created"
        else:
            user_id = existing["_id"]
            update: dict[str, Any] = {}
            if existing["display_name"] != spec["display_name"]:
                update["display_name"] = spec["display_name"]
            if sorted(existing["roles"]) != sorted(spec["roles"]):
                update["roles"] = spec["roles"]
            if reset_password:
                if password is None:
                    raise ValueError("reset_password needs a password")
                update["password_hash"] = hash_password(password)
            if update:
                update["updated_at"] = now
                db["users"].update_one({"_id": user_id}, {"$set": update})
            outcome = "updated" if update else "unchanged"
        if outcome != "unchanged":
            audit.record(
                db,
                f"user.{outcome}",
                "user",
                user_id,
                audit.SYSTEM_ACTOR,
                details={"roles": ",".join(spec["roles"]), "password_changed": outcome == "created" or reset_password},
            )
        report.append({"user_id": user_id, "email": email, "roles": spec["roles"], "outcome": outcome})
    return report
