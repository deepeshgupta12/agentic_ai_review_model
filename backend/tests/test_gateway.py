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


class FakeModels:
    def __init__(self, missing=(), error=None):
        self.missing = set(missing)
        self.error = error
        self.calls = []

    def retrieve(self, model_id):
        self.calls.append(model_id)
        if self.error is not None:
            raise self.error
        if model_id in self.missing:
            raise api_error(anthropic.NotFoundError, 404)
        return SimpleNamespace(id=model_id, display_name=f"Display {model_id}")


class FakeClient:
    def __init__(self, *outcomes, models=None):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = self
        self.models = models or FakeModels()

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


def test_configured_model_ids_are_confirmed_once_each(settings, contracts):
    models = FakeModels()
    report = gateway(settings, contracts, FakeClient(models=models)).check_models()
    roles = {
        "light": settings.model_light,
        "routine": settings.model_routine,
        "reasoning": settings.model_reasoning,
        "difficult": settings.model_difficult,
    }
    assert {role: entry["model"] for role, entry in report.items()} == roles
    assert all(entry["status"] == "available" for entry in report.values())
    assert sorted(models.calls) == sorted(set(roles.values())), "each model is confirmed once"


def test_a_model_missing_for_the_account_is_reported(settings, contracts):
    report = gateway(
        settings, contracts, FakeClient(models=FakeModels(missing={settings.model_difficult}))
    ).check_models()
    assert report["difficult"]["status"] == "model_not_found" and report["routine"]["status"] == "available"


def test_model_check_without_a_key_calls_no_one(settings, contracts):
    report = ModelGateway(settings, contracts).check_models()
    assert all(entry["status"] == "access_pending" for entry in report.values())


def test_model_check_with_a_rejected_key_is_access_pending(settings, contracts):
    client = FakeClient(models=FakeModels(error=api_error(anthropic.AuthenticationError, 401)))
    report = gateway(settings, contracts, client).check_models()
    assert all(entry["status"] == "access_pending" for entry in report.values())


def test_smoke_command_skips_without_a_key(settings, contracts, monkeypatch, capsys):
    from app import cli

    assert settings.anthropic_api_key is None
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_contracts", lambda: contracts)
    assert cli.main(["smoke-model"]) == 0
    assert capsys.readouterr().out.startswith("skipped: no ANTHROPIC_API_KEY configured")


def test_smoke_command_reports_models_and_the_call(settings, contracts, monkeypatch, capsys):
    from app import cli
    from app.agents import gateway as gateway_module

    client = FakeClient(response(VALID), models=FakeModels())
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_contracts", lambda: contracts)
    monkeypatch.setattr(gateway_module, "gateway_for", lambda _db, s, c: ModelGateway(s, c, client=client))
    assert cli.main(["smoke-model"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "completed" and printed["model_outcome"] == "insufficient_evidence"
    assert printed["models"]["routine"]["status"] == "available" and printed["returned_model"] == "claude-sonnet-5"


def test_smoke_command_fails_when_a_configured_model_is_missing(settings, contracts, monkeypatch, capsys):
    from app import cli
    from app.agents import gateway as gateway_module

    client = FakeClient(response(VALID), models=FakeModels(missing={settings.model_difficult}))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_contracts", lambda: contracts)
    monkeypatch.setattr(gateway_module, "gateway_for", lambda _db, s, c: ModelGateway(s, c, client=client))
    assert cli.main(["smoke-model"]) == 1
    assert json.loads(capsys.readouterr().out)["models"]["difficult"]["status"] == "model_not_found"


def test_a_workspace_id_is_sent_as_a_client_level_header(settings, contracts):
    settings.anthropic_api_key = SecretStr("test-only-fake-key-workspace-0000")
    settings.anthropic_workspace_id = "wrkspc_01TestOnlyExample"
    client = ModelGateway(settings, contracts)._get_client()
    assert client.default_headers["anthropic-workspace-id"] == "wrkspc_01TestOnlyExample"


def test_without_a_workspace_id_no_workspace_header_is_sent(settings, contracts):
    settings.anthropic_api_key = SecretStr("test-only-fake-key-workspace-0000")
    client = ModelGateway(settings, contracts)._get_client()
    assert "anthropic-workspace-id" not in client.default_headers


def test_a_bad_request_from_the_models_api_is_reported_as_such(settings, contracts):
    client = FakeClient(models=FakeModels(error=api_error(anthropic.BadRequestError, 400)))
    report = gateway(settings, contracts, client).check_models()
    assert {entry["status"] for entry in report.values()} == {"bad_request"}


def test_a_malformed_workspace_id_is_refused():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, anthropic_workspace_id="not-a-workspace")


# --- D53: the spend cap ------------------------------------------------------------------------------------------


def ledgered(db, settings, contracts, client):
    from app.agents.spend import SpendLedger

    return ModelGateway(settings, contracts, client=client, sleep=lambda _s: None, ledger=SpendLedger(db, settings))


def test_each_call_is_priced_from_its_usage_and_recorded(db, settings, contracts):
    from app.agents.spend import SpendLedger

    client = FakeClient(response(VALID))
    result = ledgered(db, settings, contracts, client).run("routine", SCHEMA, "system", "user", purpose="test")
    expected = (120 * 2.0 + 30 * 10.0) / 1_000_000  # usage in response(): 120 in, 30 out at Sonnet 5 prices
    assert result.outcome == "completed" and abs(result.cost_usd - expected) < 1e-9
    state = SpendLedger(db, settings).state()
    assert abs(state["spent_usd"] - expected) < 1e-9 and state["reserved_usd"] == 0 and state["calls"] == 1
    entry = db["ai_model_calls"].find_one()
    assert entry["purpose"] == "test" and entry["model"] == "claude-sonnet-5" and entry["estimate_usd"] >= expected
    assert "cache_control" not in client.calls[0], "no prefix is shared between agent tasks, so no cache is written"
    settings.model_prompt_cache = True
    client = FakeClient(response(VALID))
    ledgered(db, settings, contracts, client).run("routine", SCHEMA, "system", "user", purpose="test")
    assert client.calls[0]["cache_control"] == {"type": "ephemeral"}, "switched on, prefixes are cached"


def test_a_call_that_could_exceed_the_budget_is_refused_before_it_is_made(db, settings, contracts):
    settings.model_budget_usd = 0.001  # less than one worst-case call (16,000 output tokens at $10 per million)
    client = FakeClient(response(VALID))
    result = ledgered(db, settings, contracts, client).run("routine", SCHEMA, "system", "user")
    assert result.outcome == "failed" and result.error["code"] == "budget_exhausted" and client.calls == []
    small = ledgered(db, settings, contracts, FakeClient(response(VALID))).run(
        "routine", SCHEMA, "system", "user", max_tokens=40
    )
    assert small.outcome == "completed", "a call bounded to fit is allowed"


def test_a_failed_call_releases_its_reservation_and_costs_nothing(db, settings, contracts):
    import anthropic

    from app.agents.spend import SpendLedger

    client = FakeClient(api_error(anthropic.BadRequestError, 400))
    result = ledgered(db, settings, contracts, client).run("routine", SCHEMA, "system", "user")
    assert result.error["code"] == "bad_request" and result.cost_usd == 0
    state = SpendLedger(db, settings).state()
    assert state["spent_usd"] == 0 and state["reserved_usd"] == 0 and state["calls"] == 1


def test_live_calls_need_the_ledger_and_a_priced_model(db, settings, contracts):
    from pydantic import SecretStr

    settings.anthropic_api_key = SecretStr("sk-ant-test-not-a-real-key")
    unmetered = ModelGateway(settings, contracts).run("routine", SCHEMA, "system", "user")
    assert unmetered.error["code"] == "no_spend_ledger", "no live call escapes the budget"
    settings.model_prices = {}
    unpriced = ledgered(db, settings, contracts, FakeClient(response(VALID))).run("routine", SCHEMA, "system", "user")
    assert unpriced.error["code"] == "price_unknown"


def test_two_workers_cannot_overspend_together(db, settings):
    from app.agents.spend import SpendLedger

    settings.model_budget_usd = 1.0
    first, second = SpendLedger(db, settings), SpendLedger(db, settings)
    assert first.reserve("claude-sonnet-5", 0.6, batch=False) is not None
    assert second.reserve("claude-sonnet-5", 0.6, batch=False) is None, "0.6 + 0.6 would pass the 1.0 limit"
    assert second.reserve("claude-sonnet-5", 0.4, batch=False) is not None


def test_batch_and_cache_prices(settings):
    from app.agents.spend import actual_usd

    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert actual_usd(settings, "claude-haiku-5-5", usage, batch=False) == round(0.10 + 0.50 + 0.01, 6)
    assert actual_usd(settings, "claude-haiku-5-5", usage, batch=True) == round((0.10 + 0.50 + 0.01) / 2, 6)


class FakeBatches:
    """messages.batches stand-in: results are given per custom ID as response() messages or error types."""

    def __init__(self, outcomes, status="ended"):
        self.outcomes, self.status, self.created = outcomes, status, []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_test", processing_status="in_progress")

    def retrieve(self, message_batch_id):
        return SimpleNamespace(id=message_batch_id, processing_status=self.status)

    def results(self, message_batch_id):
        for custom_id, outcome in self.outcomes.items():
            if isinstance(outcome, str):
                yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=outcome))
            else:
                yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=outcome))


def batch_gateway(db, settings, contracts, batches):
    from app.agents.gateway import BatchGateway

    client = FakeClient()
    client.batches = batches
    return BatchGateway(ledgered(db, settings, contracts, client), db)


def test_a_batch_reserves_its_worst_case_at_half_price_and_settles_once(db, settings, contracts):
    from app.agents.spend import SpendLedger

    batches = FakeBatches({"a": response(VALID), "b": response(text="not json"), "c": "errored"})
    bg = batch_gateway(db, settings, contracts, batches)
    items = [("a", "first"), ("b", "second"), ("c", "third")]
    record = bg.submit("job:1", "light", SCHEMA, "system", items, max_tokens=200, purpose="test-batch")
    assert (
        record["status"] == "submitted"
        and record["batch_id"] == "msgbatch_test"
        and record["model"] == "claude-haiku-5-5"
    )
    assert bg.submit("job:1", "light", SCHEMA, "system", items, max_tokens=200, purpose="test-batch")["_id"] == "job:1"
    assert len(batches.created) == 1, "the same key never submits twice"
    params = batches.created[0][0]["params"]
    assert params["output_config"]["format"]["type"] == "json_schema" and "cache_control" not in params
    assert SpendLedger(db, settings).state()["reserved_usd"] == record["reserved_usd"] > 0
    assert bg.status("job:1") == "ended"
    results = bg.collect("job:1")
    assert results["a"].outcome == "completed" and results["a"].data == VALID
    assert results["b"].error["code"] == "invalid_output" and results["c"].error["code"] == "batch_errored"
    state = SpendLedger(db, settings).state()
    two_messages = 2 * (120 * 0.10 + 30 * 0.50) / 1_000_000 / 2  # two billed messages at Haiku 5.5 batch prices
    assert state["reserved_usd"] == 0 and abs(state["spent_usd"] - two_messages) < 1e-9
    bg.collect("job:1")
    assert abs(SpendLedger(db, settings).state()["spent_usd"] - two_messages) < 1e-9, "collected twice, settled once"


def test_a_batch_that_does_not_fit_the_budget_is_not_submitted(db, settings, contracts):
    settings.model_budget_usd = 0.000001
    batches = FakeBatches({})
    record = batch_gateway(db, settings, contracts, batches).submit(
        "job:2", "light", SCHEMA, "system", [("a", "x")], max_tokens=200, purpose="test"
    )
    assert record["error"]["code"] == "budget_exhausted" and batches.created == []
