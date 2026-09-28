"""Request dependencies: database, settings, the signed-in principal and role checks.

Roles are read from contracts/v1/routes.json for the operation, so the API cannot
allow a role the contract does not (D22, approval item H). Every mutation also
needs the session's CSRF token. The actor is always derived from the session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from pymongo.database import Database

from app.auth.sessions import CSRF_HEADER, SESSION_COOKIE, csrf_matches, load_session
from app.config import Settings, get_settings
from app.contracts import ContractStore, get_contracts
from app.db import get_db
from app.errors import ApiError
from app.ids import ID_PATTERN

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def db_dep() -> Database[dict[str, Any]]:
    return get_db()


def settings_dep() -> Settings:
    return get_settings()


def contracts_dep() -> ContractStore:
    return get_contracts()


@dataclass
class Principal:
    user: dict[str, Any]
    session: dict[str, Any]
    role: str  # the role that authorised this action (recorded in audits)

    @property
    def user_id(self) -> str:
        return str(self.user["_id"])

    @property
    def actor(self) -> dict[str, Any]:
        return {"kind": "user", "user_id": self.user_id, "role": self.role}


def signed_in(
    request: Request,
    db: Database[dict[str, Any]] = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = load_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    user = db["users"].find_one({"_id": session["user_id"], "active": True})
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    return user, session


def require(operation_id: str) -> Callable[..., Principal]:
    """Dependency for a session operation: signed in, allowed role, CSRF on mutations."""

    def dependency(
        request: Request,
        identity: tuple[dict[str, Any], dict[str, Any]] = Depends(signed_in),
        contracts: ContractStore = Depends(contracts_dep),
    ) -> Principal:
        user, session = identity
        allowed = contracts.roles_for(operation_id)
        held = [role for role in allowed if role in user.get("roles", [])]
        if not held:
            raise ApiError(403, "forbidden", "Your role does not allow this action")
        if request.method in MUTATING and not csrf_matches(session, request.headers.get(CSRF_HEADER)):
            raise ApiError(403, "forbidden", "Missing or invalid CSRF token")
        return Principal(user=user, session=session, role=held[0])

    dependency.__name__ = f"require_{operation_id}"
    return dependency


def contract_body(contracts: ContractStore, body: Any, ref: str) -> dict[str, Any]:
    """The request body checked against its contract schema; 422 with field messages otherwise."""
    problems = contracts.errors(body, ref)
    if problems:
        fields = [{"path": p.split(": ", 1)[0], "message": p.split(": ", 1)[-1][:300]} for p in problems[:10]]
        raise ApiError(422, "validation_failed", "The request does not match the contract", fields=fields)
    return dict(body)


def known_id(value: str, prefix: str) -> str:
    """A path ID with the right prefix, else 404 (a malformed ID never reveals whether a record exists)."""
    if not ID_PATTERN.match(value) or not value.startswith(f"{prefix}_"):
        raise ApiError(404, "not_found", "Not found")
    return value
