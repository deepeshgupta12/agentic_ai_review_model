"""UC-23: settings fail fast in live mode; logs are JSON and never carry secrets (Step 03.2, 03.9)."""

from __future__ import annotations

import io
import json
import logging

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Mode, Settings
from app.ids import id_prefix, new_id
from app.observability import JsonFormatter, log_event, redact, register_secrets, request_id_var


def test_live_mode_without_secrets_fails_clearly():
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, app_mode=Mode.LIVE)
    assert "SESSION_SECRET" in str(info.value) and "REVALIDATION_SECRET" in str(info.value)


def test_live_mode_rejects_short_secrets():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_mode=Mode.LIVE,
            session_secret=SecretStr("short"),
            revalidation_secret=SecretStr("short"),
        )


def test_a_failed_start_does_not_echo_configured_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-fake-key-echo-check-0000")
    monkeypatch.setenv("SESSION_SECRET", "short-secret-echo-check")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, app_mode=Mode.LIVE)
    message = str(info.value)
    assert "SESSION_SECRET" in message
    assert "echo-check" not in message and "input_value" not in message


def test_live_mode_with_secrets_starts():
    settings = Settings(
        _env_file=None, app_mode=Mode.LIVE, session_secret=SecretStr("s" * 40), revalidation_secret=SecretStr("r" * 40)
    )
    assert settings.app_mode is Mode.LIVE


def test_fixture_mode_gets_an_ephemeral_session_secret():
    a, b = Settings(_env_file=None), Settings(_env_file=None)
    assert a.session_secret is not None and a.session_secret.get_secret_value() != b.session_secret.get_secret_value()


def test_credentials_are_optional_and_reported_by_name():
    settings = Settings(_env_file=None, brave_search_api_key=SecretStr("brave-key-123456"))
    assert settings.credential_present("BRAVE_SEARCH_API_KEY") and not settings.credential_present("YOUTUBE_API_KEY")


def test_model_ids_come_from_configuration():
    settings = Settings(_env_file=None, model_routine="claude-haiku-4-5")
    assert settings.model_for_role("routine") == "claude-haiku-4-5"


def test_ids_have_prefix_and_ulid():
    value = new_id("prj")
    assert id_prefix(value) == "prj" and len(value) == 30
    with pytest.raises(ValueError):
        new_id("xyz")


def test_redaction_masks_known_secret_shapes_and_registered_values():
    register_secrets(["my-registered-secret-value"])
    text = redact("key sk-ant-abcdefghijklmnop, password=hunter2hunter2, value my-registered-secret-value")
    assert (
        "sk-ant-abcdefghijklmnop" not in text
        and "hunter2hunter2" not in text
        and "my-registered-secret-value" not in text
    )


def test_logs_are_json_with_request_id_and_redacted_fields():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test-json")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    token = request_id_var.set("req_abc12345")
    try:
        log_event(logger, "called provider", api_key="sk-ant-shouldnotappear123", count=3)
    finally:
        request_id_var.reset(token)
    entry = json.loads(stream.getvalue())
    assert entry["request_id"] == "req_abc12345" and entry["count"] == 3
    assert "sk-ant-shouldnotappear123" not in stream.getvalue()


def test_a_failed_login_never_logs_the_password(api, make_user, caplog):
    user = make_user(["analyst"])
    with caplog.at_level(logging.DEBUG):
        api.post("/v1/auth/login", json={"email": user["email"], "password": "typed-password-should-not-leak"})
    assert "typed-password-should-not-leak" not in caplog.text


def test_unknown_route_uses_the_error_envelope(api, contracts):
    response = api.get("/v1/does-not-exist")
    assert response.status_code == 404
    assert contracts.errors(response.json(), "common.schema.json#/$defs/ErrorEnvelope") == []


def test_invalid_body_returns_validation_failed(api, contracts):
    response = api.post("/v1/auth/login", json={"email": "x"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_failed" and body["error"]["fields"]
    assert contracts.errors(body, "common.schema.json#/$defs/ErrorEnvelope") == []


def test_ops_summary_matches_the_contract(api, make_user, db, contracts):
    from app.config import REPO_ROOT
    from app.seed.projects import seed_projects

    from .conftest import login

    seed_projects(
        db.client, db, contracts, REPO_ROOT / "contracts" / "five-project-input-template.json", REPO_ROOT / "seed"
    )
    user = make_user(["analyst"])
    login(api, user["email"])
    body = api.get("/v1/ops/summary").json()
    assert contracts.errors(body, "api.schema.json#/$defs/OpsSummary") == []
    assert len(body["projects"]) == 5


def test_readiness_reports_the_replica_set(api):
    response = api.get("/readyz")
    assert response.status_code == 200 and response.json()["replica_set"] == "rs0"
