"""UC-17: authentication, roles and CSRF (Step 03.5 acceptance: unauthorised and wrong-role
requests are rejected; CSRF is enforced on mutations)."""

from __future__ import annotations

from datetime import timedelta

from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE
from app.db import utcnow

from .conftest import PASSWORD, login


def test_login_sets_http_only_session_and_returns_contract_shape(api, make_user, contracts):
    user = make_user(["moderator"])
    response = api.post("/v1/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert response.status_code == 200
    assert contracts.errors(response.json(), "api.schema.json#/$defs/AuthSession") == []
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    csrf_cookie = next(c for c in cookies if c.startswith(f"{CSRF_COOKIE}="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_me_returns_the_signed_in_user(api, make_user, contracts):
    user = make_user(["analyst"])
    login(api, user["email"])
    response = api.get("/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["id"] == user["_id"]
    assert "password_hash" not in response.json()
    assert contracts.errors(response.json(), "api.schema.json#/$defs/UserView") == []


def test_unauthenticated_request_is_rejected_with_the_error_envelope(api, contracts):
    response = api.get("/v1/auth/me")
    assert response.status_code == 401
    assert contracts.errors(response.json(), "common.schema.json#/$defs/ErrorEnvelope") == []
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_wrong_password_is_rejected_and_audited_without_the_password(api, make_user, db):
    user = make_user(["analyst"])
    response = api.post("/v1/auth/login", json={"email": user["email"], "password": "not-the-password-123"})
    assert response.status_code == 401
    event = db["ai_audit_events"].find_one({"action": "auth.login_failed"})
    assert event is not None and event["target"]["id"] == user["_id"]
    assert "not-the-password-123" not in str(event)


def test_repeated_failures_are_rate_limited(api, make_user):
    user = make_user(["analyst"])
    for _ in range(3):
        assert (
            api.post("/v1/auth/login", json={"email": user["email"], "password": "wrong-password-xx"}).status_code
            == 401
        )
    response = api.post("/v1/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert response.status_code == 429
    assert response.json()["error"]["retryable"] is True


def test_mutation_without_csrf_token_is_rejected(api, make_user):
    user = make_user(["analyst"])
    login(api, user["email"])
    response = api.post("/v1/auth/logout")
    assert response.status_code == 403
    assert "CSRF" in response.json()["error"]["message"]


def test_logout_with_csrf_revokes_the_session(api, make_user):
    user = make_user(["analyst"])
    body = login(api, user["email"])
    old_cookie = api.cookies.get(SESSION_COOKIE)
    assert api.post("/v1/auth/logout", headers={"X-CSRF-Token": body["csrf_token"]}).status_code == 204
    api.cookies.set(SESSION_COOKIE, old_cookie)
    assert api.get("/v1/auth/me").status_code == 401


def test_tampered_cookie_is_rejected(api, make_user):
    user = make_user(["analyst"])
    login(api, user["email"])
    token, _, signature = api.cookies.get(SESSION_COOKIE).rpartition(".")
    api.cookies.set(SESSION_COOKIE, f"{token}.{'0' * len(signature)}")
    assert api.get("/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(api, make_user, db):
    user = make_user(["analyst"])
    login(api, user["email"])
    db["sessions"].update_many({"user_id": user["_id"]}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    assert api.get("/v1/auth/me").status_code == 401


def test_inactive_user_cannot_sign_in(api, make_user, db):
    user = make_user(["admin"])
    db["users"].update_one({"_id": user["_id"]}, {"$set": {"active": False}})
    assert api.post("/v1/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 401


def test_wrong_role_is_forbidden(api, make_user):
    user = make_user(["analyst"])
    login(api, user["email"])
    response = api.get("/v1/connectors/health")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_allowed_role_is_accepted_and_response_matches_contract(api, make_user, contracts):
    user = make_user(["researcher"])
    login(api, user["email"])
    response = api.get("/v1/connectors/health")
    assert response.status_code == 200
    assert contracts.errors(response.json(), "api.schema.json#/$defs/ConnectorHealthList") == []
    assert {c["status"] for c in response.json()["connectors"]} == {"access_pending"}


def test_roles_come_from_the_contract(api, make_user, contracts):
    """Every implemented session operation allows exactly the roles in routes.json."""
    implemented = {
        "getMe": ("GET", "/v1/auth/me"),
        "getOpsSummary": ("GET", "/v1/ops/summary"),
        "getConnectorHealth": ("GET", "/v1/connectors/health"),
        "listJobs": ("GET", "/v1/ops/jobs"),
    }
    for role in ("admin", "researcher", "moderator", "publisher", "analyst"):
        api.cookies.clear()
        user = make_user([role])
        login(api, user["email"])
        for operation, (method, path) in implemented.items():
            allowed = role in contracts.roles_for(operation)
            status = api.request(method, path).status_code
            assert (status == 200) == allowed, (role, operation, status)
