"""The common connector interface (docs/06): capabilities, discover, fetch_item, fetch_thread, list_updates,
check_availability and health. An unsupported capability raises CapabilityUnsupported instead of returning
nothing; a provider problem raises ProviderError with a safe code and whether a retry could help."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.sources.store import Item

CAPABILITIES = ("discover", "fetch_item", "fetch_thread", "list_updates", "check_availability", "health")


class CapabilityUnsupported(Exception):
    def __init__(self, connector_id: str, capability: str) -> None:
        super().__init__(f"{connector_id} does not support {capability}")
        self.connector_id, self.capability = connector_id, capability


class ProviderError(Exception):
    """Safe message only: never a credential or a raw provider body."""

    def __init__(self, code: str, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable, self.status = code, message[:300], retryable, status


class QuotaExhausted(ProviderError):
    def __init__(self, connector_id: str, bucket: str) -> None:
        super().__init__(
            "quota_exhausted", f"{connector_id} {bucket} quota is used up for this window", retryable=False
        )


@dataclass
class Page:
    items: list[Item]
    next_cursor: str | None
    attempted: int = 1  # provider requests made for this page
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> count, for coverage notes


@dataclass
class Availability:
    state: str  # present | changed | gone | unknown
    detail: str
    item: Item | None = None


class Connector:
    id: str = ""
    supports: frozenset[str] = frozenset()

    def _unsupported(self, capability: str) -> CapabilityUnsupported:
        return CapabilityUnsupported(self.id, capability)

    def capabilities(self) -> dict[str, bool]:
        return {c: c in self.supports for c in CAPABILITIES}

    def discover(self, query: dict[str, Any], cursor: str | None) -> Page:
        raise self._unsupported("discover")

    def fetch_item(self, ref: str) -> Item:
        raise self._unsupported("fetch_item")

    def fetch_thread(self, parent: dict[str, Any], cursor: str | None) -> Page:
        raise self._unsupported("fetch_thread")

    def list_updates(self, since: str | None) -> Page:
        raise self._unsupported("list_updates")

    def check_availability(self, source: dict[str, Any]) -> Availability:
        raise self._unsupported("check_availability")

    def health(self) -> dict[str, Any]:
        raise self._unsupported("health")
