"""UC-21: the Claude model gateway with a recorded fake client (Step 03.7: refusal and incomplete handling,
one bounded repair, retries on transient errors, usage recording; no key means access_pending)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
from pydantic import SecretStr

from app.agents.gateway import ModelGateway

SCHEMA = "agents.schema.json#/$defs/SynthesisResult"
VALID = {"outcome": "insufficient_evidence", "findings": [], "insufficiency_note": "No evidence supplied"}


def response(payload=None, *, stop_reason="end_turn", text=None, model="claude-sonnet-5", request_id="req_test"):
    body = text if text is not None else json.dumps(payload)
    message = SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30, cache_read_input_tokens=0),
    )
    message._request_id = request_id
    return message


def api_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(f"HTTP {status}", response=httpx2.Response(status, request=request), body=None)


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def gateway(settings, contracts, client):
    return ModelGateway(settings, contracts, client=client, sleep=lambda _s: None)


def test_valid_output_is_returned_with_usage_and_request_id(settings, contracts):
    client = FakeClient(response(VALID))
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "system", "user")
    assert result.outcome == "completed" and result.data == VALID
    assert result.returned_model == "claude-sonnet-5" and result.provider_request_id == "req_test"
    assert result.usage["input_tokens"] == 120 and not result.repair_used


def test_request_uses_the_configured_model_and_the_bundled_contract_schema(settings, contracts):
    client = FakeClient(response(VALID))
    gateway(settings, contracts, client).run("difficult", SCHEMA, "system", "user")
    call = client.calls[0]
    assert call["model"] == settings.model_difficult
    schema = call["output_config"]["format"]["schema"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert schema == contracts.bundle(SCHEMA)
    assert "temperature" not in call and "top_p" not in call


def test_refusal_is_a_failure_not_parsed(settings, contracts):
    result = gateway(settings, contracts, FakeClient(response(VALID, stop_reason="refusal"))).run(
        "routine", SCHEMA, "s", "u"
    )
    assert result.outcome == "failed" and result.error["code"] == "refusal" and result.data is None


def test_truncated_output_is_incomplete(settings, contracts):
    result = gateway(settings, contracts, FakeClient(response(VALID, stop_reason="max_tokens"))).run(
        "routine", SCHEMA, "s", "u"
    )
    assert result.error["code"] == "incomplete"


def test_one_repair_fixes_invalid_output(settings, contracts):
    bad = {"outcome": "failed", "findings": [], "insufficiency_note": None}
    client = FakeClient(response(bad), response(VALID))
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u")
    assert result.outcome == "completed" and result.repair_used
    assert "failed validation" in client.calls[1]["messages"][-1]["content"]


def test_second_invalid_output_fails_without_a_third_try(settings, contracts):
    bad = {"outcome": "failed", "findings": [], "insufficiency_note": None}
    client = FakeClient(response(bad), response(text="not json"))
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u")
    assert result.outcome == "failed" and result.error["code"] == "invalid_output" and len(client.calls) == 2


def test_rate_limit_and_overload_are_retried(settings, contracts):
    client = FakeClient(
        api_error(anthropic.RateLimitError, 429), api_error(anthropic.InternalServerError, 529), response(VALID)
    )
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u")
    assert result.outcome == "completed" and result.attempts == 3


def test_retries_stop_at_the_attempt_budget(settings, contracts):
    client = FakeClient(*[api_error(anthropic.RateLimitError, 429) for _ in range(5)])
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u")
    assert result.outcome == "failed" and result.error["code"] == "provider_unavailable"
    assert len(client.calls) == settings.model_max_attempts


def test_unknown_model_fails_fast(settings, contracts):
    client = FakeClient(api_error(anthropic.NotFoundError, 404))
    result = gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u")
    assert result.error["code"] == "model_not_found" and len(client.calls) == 1


def test_rejected_key_is_access_pending(settings, contracts):
    client = FakeClient(api_error(anthropic.AuthenticationError, 401))
    assert gateway(settings, contracts, client).run("routine", SCHEMA, "s", "u").error["code"] == "access_pending"


def test_no_key_means_access_pending_without_calling_anyone(settings, contracts):
    assert settings.anthropic_api_key is None
    result = ModelGateway(settings, contracts).run("routine", SCHEMA, "s", "u")
    assert result.outcome == "failed" and result.error["code"] == "access_pending" and result.attempts == 0


def test_a_configured_key_makes_the_gateway_available(settings, contracts):
    settings.anthropic_api_key = SecretStr("test-only-fake-key-0000000000")
    assert ModelGateway(settings, contracts).available
