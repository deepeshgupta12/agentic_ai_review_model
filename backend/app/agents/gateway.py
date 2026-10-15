"""Model gateway around the Anthropic SDK (docs/01, docs/04 shared execution envelope, D10, D11).

- The model comes from configuration by role (routine, reasoning, difficult); no IDs in code.
- Output uses Claude structured outputs with the agent's contract schema, bundled into one
  self-contained schema (`output_config.format`), then validated against the full contract.
- Refusals and truncated responses are explicit failures, never parsed.
- Invalid output gets one bounded repair attempt.
- Rate limits, overload, server errors and connection problems retry with backoff under
  the configured attempt budget (on top of the SDK's own retries); other errors fail fast.
- Every call returns what an AgentRun record needs: models, stop reason, usage, request ID.
- `check_models` confirms through the Models API that each configured ID exists for the account.
- Spend (D53): a live call needs the spend ledger; it reserves its worst-case cost first and is refused with
  `budget_exhausted` when that does not fit, then records its actual cost.
- Prompt caching (D65): one explicit breakpoint on the agent's instructions, the prefix all its tasks share, when it
  reaches the model's minimum cacheable length (`cached_system`). The task's own evidence is never marked: no other
  call repeats it. Cache writes and reads are priced and recorded like any other tokens.
A missing API key is `access_pending`, not a crash (D06).
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from app.agents.spend import (
    CHARS_PER_TOKEN,
    PriceUnknown,
    Reservation,
    SpendLedger,
    estimate_input_tokens,
    worst_case_usd,
)
from app.config import Settings
from app.contracts import ContractStore
from app.db import utcnow
from app.observability import log_event

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
ROLES = ("light", "routine", "reasoning", "difficult")


class BatchesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...

    def retrieve(self, message_batch_id: str) -> Any: ...

    def results(self, message_batch_id: str) -> Any: ...


class MessagesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...

    @property
    def batches(self) -> BatchesAPI: ...


class ModelsAPI(Protocol):
    def retrieve(self, model_id: str) -> Any: ...


class ClientLike(Protocol):
    @property
    def messages(self) -> MessagesAPI: ...

    @property
    def models(self) -> ModelsAPI: ...


@dataclass
class GatewayResult:
    outcome: str  # completed | failed (model-reported outcomes live inside `data`)
    data: dict[str, Any] | None
    requested_model: str
    returned_model: str | None = None
    stop_reason: str | None = None
    usage: dict[str, int | float | None] = field(
        default_factory=lambda: {
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_input_tokens": None,
            "audio_seconds": None,
        }
    )
    provider_request_id: str | None = None
    attempts: int = 0
    repair_used: bool = False
    error: dict[str, str] | None = None
    cost_usd: float = 0.0  # summed over every billed round (D53)
    cache_write_tokens: int = 0


def cached_system(settings: Settings, model: str, system: str, ttl: str) -> tuple[str | list[dict[str, Any]], int]:
    """The system prompt as sent, and how many of its tokens may be written to the cache (D65).

    With caching on and the instructions at or above the model's minimum cacheable length, the prompt becomes one text
    block carrying the cache breakpoint; otherwise it is sent as plain text (the API would not cache it anyway)."""
    tokens = int(len(system) / CHARS_PER_TOKEN)
    minimum = settings.model_cache_min_tokens.get(model)
    if not settings.model_prompt_cache or minimum is None or tokens < minimum:
        return system, 0
    control: dict[str, str] = {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": ttl}
    return [{"type": "text", "text": system, "cache_control": control}], tokens


class ModelGateway:
    def __init__(
        self,
        settings: Settings,
        contracts: ContractStore,
        client: ClientLike | None = None,
        sleep: Any = time.sleep,
        ledger: SpendLedger | None = None,
    ) -> None:
        self.settings = settings
        self.contracts = contracts
        self._client: Any = client
        self._sleep = sleep
        self.ledger = ledger

    @property
    def available(self) -> bool:
        return self._client is not None or self.settings.credential_present("ANTHROPIC_API_KEY")

    def _get_client(self) -> ClientLike:
        if self._client is None:
            assert self.settings.anthropic_api_key is not None
            workspace = self.settings.anthropic_workspace_id
            # The gateway retries itself (model_max_attempts); the SDK does not retry inside it, and a call waits at
            # most model_timeout_seconds, so a stalled connection cannot hold a job for an hour (audit, 14 Oct 2026).
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                max_retries=0,
                timeout=self.settings.model_timeout_seconds,
                default_headers={"anthropic-workspace-id": workspace} if workspace else None,
            )
        return self._client

    def check_models(self) -> dict[str, dict[str, str | None]]:
        """Per role: the configured model ID and whether this account can use it (Step 03.2)."""
        found: dict[str, dict[str, str | None]] = {}
        report: dict[str, dict[str, str | None]] = {}
        for role in ROLES:
            model = self.settings.model_for_role(role)
            if model not in found:
                found[model] = self._retrieve_model(model)
            report[role] = {"model": model, **found[model]}
        return report

    def _retrieve_model(self, model: str) -> dict[str, str | None]:
        if not self.available:
            return {"status": "access_pending", "resolved_id": None, "display_name": None}
        try:
            info = self._get_client().models.retrieve(model)
        except anthropic.NotFoundError:
            return {"status": "model_not_found", "resolved_id": None, "display_name": None}
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            return {"status": "access_pending", "resolved_id": None, "display_name": None}
        except anthropic.BadRequestError:
            return {"status": "bad_request", "resolved_id": None, "display_name": None}
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            return {"status": "provider_unavailable", "resolved_id": None, "display_name": None}
        return {
            "status": "available",
            "resolved_id": getattr(info, "id", None),
            "display_name": getattr(info, "display_name", None),
        }

    def run(
        self,
        role: str,
        schema_ref: str,
        system: str,
        user_content: str | list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        purpose: str = "",
    ) -> GatewayResult:
        """`user_content` is text, or content blocks (text and images) for the vision agent A03 (Step 06.5).
        `purpose` labels the spend ledger entry (agent or check name)."""
        model = self.settings.model_for_role(role)
        result = GatewayResult(outcome="failed", data=None, requested_model=model)
        if not self.available:
            result.error = {"code": "access_pending", "message": "No Anthropic API key configured"}
            return result
        if self._client is None and self.ledger is None:
            result.error = {"code": "no_spend_ledger", "message": "Live calls need the spend ledger (D53)"}
            return result
        schema = self.contracts.bundle(schema_ref)
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        limit = max_tokens or self.settings.model_max_output_tokens
        ttl = self.settings.model_cache_ttl
        system_param, cached_tokens = cached_system(self.settings, model, system, ttl)
        for repair_round in range(2):
            reservation = None
            if self.ledger is not None:
                try:
                    input_tokens = estimate_input_tokens(system, _flatten(messages))
                    worst = worst_case_usd(
                        self.settings, model, input_tokens, limit, batch=False, cached_tokens=cached_tokens, ttl=ttl
                    )
                    reservation = self.ledger.reserve(model, worst, batch=False)
                except PriceUnknown as exc:
                    result.error = {"code": "price_unknown", "message": str(exc)}
                    return result
                if reservation is None:
                    state = self.ledger.state()
                    result.error = {
                        "code": "budget_exhausted",
                        "message": f"Model budget reached: {state['spent_usd']:.4f} "
                        f"of {state['limit_usd']:.2f} USD spent",
                    }
                    return result
            try:
                response = self._call(model, system_param, messages, schema, limit, result)
            except Exception:
                # an error outside the provider's own (for example the SDK refusing the request): the hold is released
                if reservation is not None and self.ledger is not None:
                    self.ledger.settle(
                        reservation,
                        None,
                        purpose=purpose or schema_ref.rsplit("/", 1)[-1],
                        outcome="not_billed",
                        error_code="exception",
                        request_id=None,
                    )
                raise
            if reservation is not None and self.ledger is not None:
                billed = self._billed_usage(response)
                result.cost_usd += self.ledger.settle(
                    reservation,
                    billed,
                    purpose=purpose or schema_ref.rsplit("/", 1)[-1],
                    outcome="returned" if response is not None else "not_billed",
                    error_code=(result.error or {}).get("code") if response is None else None,
                    request_id=getattr(response, "_request_id", None),
                )
            if response is None:
                return result
            text = self._read(response, result)
            if text is None:
                return result
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                problems = ["output was not valid JSON"]
            else:
                problems = self.contracts.errors(data, schema_ref)
                if not problems:
                    result.outcome, result.data = "completed", data
                    return result
            if repair_round == 0:
                result.repair_used = True
                messages += [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "That output failed validation: "
                        + "; ".join(problems[:5])
                        + ". Return corrected JSON only.",
                    },
                ]
        result.error = {"code": "invalid_output", "message": "Output failed validation after one repair"}
        return result

    def _call(
        self,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        result: GatewayResult,
    ) -> Any | None:
        for attempt in range(1, self.settings.model_max_attempts + 1):
            result.attempts += 1
            try:
                return self._get_client().messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
            except anthropic.NotFoundError:
                result.error = {"code": "model_not_found", "message": f"Model {model} is not available to this account"}
                return None
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                result.error = {"code": "access_pending", "message": "The API key was rejected"}
                return None
            except anthropic.BadRequestError as exc:
                result.error = {"code": "bad_request", "message": str(exc.message)[:300]}
                return None
            except anthropic.APIStatusError as exc:
                if exc.status_code not in RETRYABLE_STATUS:
                    result.error = {"code": "provider_error", "message": f"HTTP {exc.status_code}"}
                    return None
                error = {"code": "provider_unavailable", "message": f"HTTP {exc.status_code}"}
            except (anthropic.APIConnectionError, anthropic.APITimeoutError):
                error = {"code": "provider_unavailable", "message": "Connection problem"}
            log_event(
                logger, "model call retry", level=logging.WARNING, model=model, attempt=attempt, error=error["code"]
            )
            if attempt < self.settings.model_max_attempts:
                self._sleep(random.uniform(0, min(30.0, 2.0 * 2 ** (attempt - 1))))  # noqa: S311 - jitter only
        result.error = error
        return None

    @staticmethod
    def _billed_usage(response: Any) -> dict[str, Any] | None:
        usage = getattr(response, "usage", None) if response is not None else None
        if usage is None:
            return None
        creation = getattr(usage, "cache_creation", None)
        return {
            "input_tokens": getattr(usage, "input_tokens", None) or 0,
            "output_tokens": getattr(usage, "output_tokens", None) or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
            # 1-hour writes cost more than 5-minute ones (D65); the breakdown is reported when the cache was written
            "cache_creation_1h_input_tokens": getattr(creation, "ephemeral_1h_input_tokens", None) or 0,
        }

    @staticmethod
    def _read(response: Any, result: GatewayResult) -> str | None:
        result.returned_model = getattr(response, "model", None)
        result.stop_reason = getattr(response, "stop_reason", None)
        result.provider_request_id = getattr(response, "_request_id", None)
        usage = getattr(response, "usage", None)
        if usage is not None:
            result.usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "audio_seconds": None,
            }
            result.cache_write_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        if result.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            result.error = {"code": "refusal", "message": f"The model declined (category: {category or 'unspecified'})"}
            return None
        if result.stop_reason == "max_tokens":
            result.error = {"code": "incomplete", "message": "Output hit the token limit"}
            return None
        text = next(
            (block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"), None
        )
        if text is None:
            result.error = {"code": "invalid_output", "message": "No text block in the response"}
        return text


def _flatten(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All content blocks of a conversation, for the input-size estimate."""
    blocks: list[dict[str, Any]] = []
    for message in messages:
        content = message["content"]
        blocks += [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    return blocks


def gateway_for(db: Any, settings: Settings, contracts: ContractStore) -> ModelGateway:
    """The gateway for live work: every call is checked against and recorded in the spend ledger (D53)."""
    return ModelGateway(settings, contracts, ledger=SpendLedger(db, settings))


BATCHES = "ai_model_batches"


class BatchGateway:
    """Message Batches for bulk work that can wait (Step 08.1, D53): half price, results within hours (usually
    minutes). Submitting reserves the whole batch's worst case against the budget and records the batch before
    anything else; collecting validates every result against the agent's contract and settles the actual cost
    exactly once. A batch that fails to submit releases nothing until it is known not to exist: the budget errs on
    the safe side."""

    def __init__(self, gateway: ModelGateway, db: Any) -> None:
        if gateway.ledger is None and gateway._client is None:
            raise ValueError("batches need the spend ledger")
        self.gateway, self.db = gateway, db

    def submit(
        self,
        key: str,
        role: str,
        schema_ref: str,
        system: str,
        items: list[tuple[str, str | list[dict[str, Any]]]],
        *,
        max_tokens: int,
        purpose: str,
    ) -> dict[str, Any]:
        """`key` makes the submission idempotent (for example the job's logical key): the same key returns the
        batch already submitted. Returns the batch record, or one with `error` when it could not be submitted."""
        existing = self.db[BATCHES].find_one({"_id": key})
        if existing is not None:
            return existing
        g = self.gateway
        model = g.settings.model_for_role(role)
        if not g.available:
            return {"_id": key, "error": {"code": "access_pending", "message": "No Anthropic API key configured"}}
        reservation = None
        ttl = g.settings.model_batch_cache_ttl
        system_param, cached_tokens = cached_system(g.settings, model, system, ttl)
        if g.ledger is not None:
            try:
                worst = sum(
                    worst_case_usd(
                        g.settings,
                        model,
                        estimate_input_tokens(system, _flatten([{"content": content}])),
                        max_tokens,
                        batch=True,
                        cached_tokens=cached_tokens,
                        ttl=ttl,
                    )
                    for _, content in items
                )
            except PriceUnknown as exc:
                return {"_id": key, "error": {"code": "price_unknown", "message": str(exc)}}
            reservation = g.ledger.reserve(model, round(worst, 6), batch=True)
            if reservation is None:
                return {"_id": key, "error": {"code": "budget_exhausted", "message": "Model budget reached"}}
        schema = g.contracts.bundle(schema_ref)
        record = {
            "_id": key,
            "status": "submitting",
            "model": model,
            "role": role,
            "schema_ref": schema_ref,
            "purpose": purpose,
            "custom_ids": [custom_id for custom_id, _ in items],
            "budget": reservation.budget_id if reservation else None,
            "reserved_usd": reservation.amount_usd if reservation else 0.0,
            "batch_id": None,
            "created_at": utcnow(),
        }
        self.db[BATCHES].insert_one(record)
        requests = [
            {
                "custom_id": custom_id,
                "params": {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_param,  # the same breakpoint in every request, as Anthropic advises (D65)
                    "messages": [{"role": "user", "content": content}],
                    "output_config": {"format": {"type": "json_schema", "schema": schema}},
                },
            }
            for custom_id, content in items
        ]
        try:
            batch = g._get_client().messages.batches.create(requests=requests)
        except anthropic.APIError as exc:
            self.db[BATCHES].update_one(
                {"_id": key},
                {"$set": {"status": "failed", "error": {"code": "submit_failed", "message": str(exc)[:300]}}},
            )
            if reservation is not None and g.ledger is not None:
                g.ledger.settle(reservation, None, purpose=purpose, outcome="not_billed", error_code="submit_failed")
            return self.db[BATCHES].find_one({"_id": key}) or record
        self.db[BATCHES].update_one({"_id": key}, {"$set": {"status": "submitted", "batch_id": batch.id}})
        return self.db[BATCHES].find_one({"_id": key}) or record

    def status(self, key: str) -> str:
        record = self.db[BATCHES].find_one({"_id": key})
        if record is None or record.get("batch_id") is None:
            return "missing" if record is None else record["status"]
        if record["status"] in ("collected", "failed"):
            return record["status"]
        batch = self.gateway._get_client().messages.batches.retrieve(record["batch_id"])
        return "ended" if batch.processing_status == "ended" else "in_progress"

    def collect(self, key: str) -> dict[str, GatewayResult]:
        """Results by custom ID for an ended batch; settles the cost once (later calls re-read without settling)."""
        record = self.db[BATCHES].find_one({"_id": key})
        if record is None or record.get("batch_id") is None:
            raise ValueError(f"no submitted batch for {key}")
        g = self.gateway
        results: dict[str, GatewayResult] = {}
        total = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_creation_1h_input_tokens": 0,
        }
        for row in g._get_client().messages.batches.results(record["batch_id"]):
            result = GatewayResult(outcome="failed", data=None, requested_model=record["model"])
            outcome = getattr(row.result, "type", None)
            if outcome == "succeeded":
                message = row.result.message
                billed = ModelGateway._billed_usage(message) or {}
                for k in total:
                    total[k] += int(billed.get(k) or 0)
                text = ModelGateway._read(message, result)
                if text is not None:
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        result.error = {"code": "invalid_output", "message": "output was not valid JSON"}
                    else:
                        problems = g.contracts.errors(data, record["schema_ref"])
                        if problems:
                            result.error = {"code": "invalid_output", "message": "; ".join(problems[:3])[:300]}
                        else:
                            result.outcome, result.data = "completed", data
            else:
                result.error = {"code": f"batch_{outcome or 'unknown'}", "message": "the batch request did not succeed"}
            result.attempts = 1
            results[row.custom_id] = result
        claimed = self.db[BATCHES].update_one(
            {"_id": key, "status": "submitted"},
            {"$set": {"status": "collected", "collected_at": utcnow(), "usage": total}},
        )
        if claimed.modified_count == 1 and g.ledger is not None and record.get("budget"):
            reservation = Reservation(record["budget"], record["reserved_usd"], record["model"], True)
            cost = g.ledger.settle(reservation, total, purpose=record["purpose"], outcome="batch_collected")
            for result in results.values():  # spread the batch cost evenly for the per-task records
                result.cost_usd = round(cost / max(1, len(results)), 6)
        return results
