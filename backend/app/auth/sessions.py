"""Server-side sessions with a signed, HTTP-only cookie and a CSRF token (docs/03).

The cookie holds `<token>.<hmac>`; the database stores only sha256(token). The CSRF
token is returned at login and mirrored in a readable cookie; every mutation must
echo it in X-CSRF-Token. Logout revokes the session; sessions also expire.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.db import utcnow

SESSION_COOKIE = "sy_session"
CSRF_COOKIE = "sy_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sign(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class NewSession:
    cookie_value: str
    csrf_token: str
    expires_at: Any


def create_session(db: Database[dict[str, Any]], settings: Settings, user_id: str) -> NewSession:
    assert settings.session_secret is not None
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = utcnow()
    expires = now + timedelta(hours=settings.session_ttl_hours)
    db["sessions"].insert_one(
        {
            "_id": _sha256(token),
            "user_id": user_id,
            "csrf_hash": _sha256(csrf),
            "created_at": now,
            "expires_at": expires,
            "revoked_at": None,
        }
    )
    return NewSession(f"{token}.{_sign(token, settings.session_secret.get_secret_value())}", csrf, expires)


def load_session(db: Database[dict[str, Any]], settings: Settings, cookie_value: str | None) -> dict[str, Any] | None:
    """The live session for a cookie, or None if missing, tampered, revoked or expired."""
    if not cookie_value or "." not in cookie_value:
        return None
    assert settings.session_secret is not None
    token, _, signature = cookie_value.rpartition(".")
    if not hmac.compare_digest(signature, _sign(token, settings.session_secret.get_secret_value())):
        return None
    session = db["sessions"].find_one({"_id": _sha256(token)})
    if session is None or session["revoked_at"] is not None or session["expires_at"] <= utcnow():
        return None
    return session


def csrf_matches(session: dict[str, Any], header_value: str | None) -> bool:
    return bool(header_value) and hmac.compare_digest(session["csrf_hash"], _sha256(header_value or ""))


def revoke_session(db: Database[dict[str, Any]], session_id: str) -> None:
    db["sessions"].update_one({"_id": session_id, "revoked_at": None}, {"$set": {"revoked_at": utcnow()}})


def attempt_key(email: str, client_host: str) -> str:
    return _sha256(f"{email.strip().lower()}|{client_host}")
