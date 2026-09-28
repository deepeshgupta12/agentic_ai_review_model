"""MongoDB access: one client per process, the application database and transactions (D08).

Datetimes are stored as BSON dates in UTC and exposed as RFC 3339 strings with Z.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from app.config import Settings, get_settings


def utcnow() -> datetime:
    # MongoDB stores millisecond precision; truncate so round trips compare equal.
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_client(settings: Settings) -> MongoClient[dict[str, Any]]:
    return MongoClient(settings.mongodb_uri, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=5000, appname="sy-poc")


@lru_cache(maxsize=1)
def _client() -> MongoClient[dict[str, Any]]:
    return make_client(get_settings())


def get_db() -> Database[dict[str, Any]]:
    return _client()[get_settings().mongodb_db]


def run_in_transaction[T](client: MongoClient[dict[str, Any]], work: Callable[[ClientSession], T]) -> T:
    """Run `work` inside a majority transaction; retried by the driver on transient errors."""
    with client.start_session() as session:
        return session.with_transaction(
            work,
            read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"),
        )
