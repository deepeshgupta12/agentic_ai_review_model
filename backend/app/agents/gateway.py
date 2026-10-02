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

from app.config import Settings
from app.contracts import ContractStore
from app.observability import log_event

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
ROLES = ("routine", "reasoning", "difficult")


class MessagesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


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


class ModelGateway:
    def __init__(
        self, settings: Settings, contracts: ContractStore, client: ClientLike | None = None, sleep: Any = time.sleep
    ) -> None:
        self.settings = settings
        self.contracts = contracts
        self._client: Any = client
        self._sleep = sleep

    @property
    def available(self) -> bool:
        return self._client is not None or self.settings.credential_present("ANTHROPIC_API_KEY")

    def _get_client(self) -> ClientLike:
        if self._client is None:
            assert self.settings.anthropic_api_key is not None
            workspace = self.settings.anthropic_workspace_id
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                max_retries=2,
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
    ) -> GatewayResult:
        """`user_content` is text, or content blocks (text and images) for the vision agent A03 (Step 06.5)."""
        model = self.settings.model_for_role(role)
        result = GatewayResult(outcome="failed", data=None, requested_model=model)
        if not self.available:
            result.error = {"code": "access_pending", "message": "No Anthropic API key configured"}
            return result
        schema = self.contracts.bundle(schema_ref)
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        for repair_round in range(2):
            response = self._call(
                model, system, messages, schema, max_tokens or self.settings.model_max_output_tokens, result
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
        system: str,
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
