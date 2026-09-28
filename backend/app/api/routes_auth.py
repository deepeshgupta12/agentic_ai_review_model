"""Session lifecycle: login, logout, me (routes.json operations login, logout, getMe)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from pymongo.database import Database

from app import audit
from app.api.deps import Principal, db_dep, require, settings_dep
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE, attempt_key, create_session, revoke_session
from app.config import Settings
from app.db import iso, utcnow
from app.errors import ApiError

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def user_view(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "roles": user["roles"],
        "active": user["active"],
    }


@router.post("/login", operation_id="login", summary="Start a session")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Database[dict[str, Any]] = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    email = body.email.strip().lower()
    key = attempt_key(email, request.client.host if request.client else "unknown")
    since = utcnow() - timedelta(minutes=settings.login_window_minutes)
    failures = db["login_attempts"].count_documents({"key": key, "at": {"$gte": since}, "succeeded": False})
    if failures >= settings.login_attempts_per_window:
        raise ApiError(429, "rate_limited", "Too many attempts; try again later", retryable=True)

    user = db["users"].find_one({"email": email, "active": True})
    if user is None or not verify_password(user["password_hash"], body.password):
        db["login_attempts"].insert_one({"key": key, "at": utcnow(), "succeeded": False})
        audit.record(db, "auth.login_failed", "user", user["_id"] if user else "unknown", audit.PUBLIC_ACTOR)
        raise ApiError(401, "unauthenticated", "Email or password is incorrect")

    if needs_rehash(user["password_hash"]):
        db["users"].update_one(
            {"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.password), "updated_at": utcnow()}}
        )
    db["login_attempts"].insert_one({"key": key, "at": utcnow(), "succeeded": True})
    new = create_session(db, settings, user["_id"])
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        new.cookie_value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        new.csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    audit.record(db, "auth.login_succeeded", "user", user["_id"], audit.user_actor(user["_id"], user["roles"][0]))
    return {"user": user_view(user), "csrf_token": new.csrf_token, "expires_at": iso(new.expires_at)}


@router.post("/logout", operation_id="logout", summary="End the session", status_code=204)
def logout(
    response: Response,
    principal: Principal = Depends(require("logout")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> Response:
    revoke_session(db, principal.session["_id"])
    audit.record(db, "auth.logout", "user", principal.user_id, principal.actor)
    response.status_code = 204
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.get("/me", operation_id="getMe", summary="Current user and roles")
def me(principal: Principal = Depends(require("getMe"))) -> dict[str, Any]:
    return user_view(principal.user)
