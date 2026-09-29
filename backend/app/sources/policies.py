"""Source policies in ai_source_policies (SourcePolicy; docs/06; D22, D28, D33, D34, D38).

Versions are immutable: a change is a new policy_version. The current version of a family is the highest
accepted one in force now. Eligibility uses both: a source is stored under the version in force when it was
collected, and may be used by AI only while the family's current version still allows it, so narrowing a
policy applies at once to everything already stored.

A URL's host decides its family: a family that lists the host (or a parent domain) owns it; otherwise the
generic web family applies, which is an allow-list (its `hosts`), minus its `excluded_hosts`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.ids import new_id

COLLECTION = "ai_source_policies"
GENERIC_WEB = "web_public_pages"
# Families whose pages the web fetcher may read (by host). Others are reached only through their own API.
WEB_FETCH_FAMILIES = {GENERIC_WEB, "competitor_portals", "official_records"}
IMMUTABLE_FIELDS = (
    "collection_allowed",
    "ai_processing_allowed",
    "quotation_allowed",
    "derived_publication_allowed",
    "attribution_required",
    "retention_days",
    "hosts",
    "excluded_hosts",
    "conditions",
    "basis",
    "status",
)
RIGHTS = ("collection_allowed", "ai_processing_allowed", "quotation_allowed", "derived_publication_allowed")


class PolicyError(ValueError):
    pass


def _as_datetime(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def policy_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def seed_policies(
    client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]], contracts: ContractStore, path: Path
) -> list[dict[str, Any]]:
    """Load seed/source_policies.json. A version already stored must be unchanged (immutability)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    report: list[dict[str, Any]] = []
    for raw in data["policies"]:
        item = {"hosts": [], "excluded_hosts": [], "conditions": [], **raw}  # optional lists in the seed file

        def write(session: ClientSession, item: dict[str, Any] = item) -> dict[str, Any]:
            existing = db[COLLECTION].find_one(
                {"family": item["family"], "policy_version": item["policy_version"]}, session=session
            )
            if existing is not None:
                changed = [f for f in IMMUTABLE_FIELDS if existing[f] != item[f]]
                if changed:
                    raise PolicyError(
                        f"{item['family']} v{item['policy_version']} is stored and immutable; changed {changed}. "
                        "Create a new policy_version instead."
                    )
                return {"family": item["family"], "policy_version": item["policy_version"], "outcome": "unchanged"}
            accepted_on = item.get("accepted_on")
            doc = {
                "_id": new_id("pol"),
                "family": item["family"],
                "policy_version": item["policy_version"],
                **{f: item[f] for f in IMMUTABLE_FIELDS},
                "effective_from": _as_datetime(accepted_on) if accepted_on else utcnow(),
                "expires_at": None,
                "accepted_on": accepted_on,
                "accepted_by": item.get("accepted_by"),
            }
            problems = contracts.errors(policy_view(doc), "sources.schema.json#/$defs/SourcePolicy")
            if problems:
                raise PolicyError(f"{item['family']} v{item['policy_version']}: {problems[:3]}")
            db[COLLECTION].insert_one(doc, session=session)
            audit.record(
                db,
                "source_policy.created",
                "source_policy",
                doc["_id"],
                audit.SYSTEM_ACTOR,
                details={"family": item["family"], "policy_version": item["policy_version"], "source": "seed"},
                session=session,
            )
            return {"family": item["family"], "policy_version": item["policy_version"], "outcome": "created"}

        report.append(run_in_transaction(client, write))
    return report


def current(
    db: Database[dict[str, Any]], family: str, at: datetime | None = None, session: ClientSession | None = None
) -> dict[str, Any] | None:
    at = at or utcnow()
    return db[COLLECTION].find_one(
        {
            "family": family,
            "status": "accepted",
            "effective_from": {"$lte": at},
            "$or": [{"expires_at": None}, {"expires_at": {"$gt": at}}],
        },
        sort=[("policy_version", -1)],
        session=session,
    )


def version(
    db: Database[dict[str, Any]], ref: dict[str, Any], session: ClientSession | None = None
) -> dict[str, Any] | None:
    return db[COLLECTION].find_one({"family": ref["family"], "policy_version": ref["policy_version"]}, session=session)


def ref_of(policy: dict[str, Any]) -> dict[str, Any]:
    return {"family": policy["family"], "policy_version": policy["policy_version"]}


def ai_processing_allowed(
    db: Database[dict[str, Any]], ref: dict[str, Any], session: ClientSession | None = None
) -> bool:
    """Collected lawfully under its own version, and AI use still allowed by the family's current version."""
    stored = version(db, ref, session)
    now = current(db, ref["family"], session=session)
    return bool(stored and stored["collection_allowed"] and now and now["ai_processing_allowed"])


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, listed: list[str]) -> bool:
    return any(host == h or host.endswith("." + h) for h in listed)


@dataclass
class Resolution:
    host: str
    family: str | None
    policy: dict[str, Any] | None
    may_collect: bool
    reason: str


def resolve(db: Database[dict[str, Any]], url: str, session: ClientSession | None = None) -> Resolution:
    """Which policy governs this URL, and whether its content may be collected."""
    host = host_of(url)
    if not host:
        return Resolution(host, None, None, False, "no host in the URL")
    families = {
        p["family"]: p
        for p in (current(db, f, session=session) for f in db[COLLECTION].distinct("family", session=session))
        if p is not None
    }
    for family, policy in sorted(families.items()):
        if family != GENERIC_WEB and _matches(host, policy["hosts"]):
            ok = policy["collection_allowed"]
            reason = f"{family} v{policy['policy_version']}" + ("" if ok else " does not allow collection")
            return Resolution(host, family, policy, ok, reason)
    web = families.get(GENERIC_WEB)
    if web is None:
        return Resolution(host, None, None, False, "no generic web policy")
    if _matches(host, web["excluded_hosts"]):
        return Resolution(host, GENERIC_WEB, web, False, f"{host} is excluded from {GENERIC_WEB}")
    if not _matches(host, web["hosts"]):
        return Resolution(host, GENERIC_WEB, web, False, f"{host} is not on the {GENERIC_WEB} allow-list")
    return Resolution(host, GENERIC_WEB, web, web["collection_allowed"], f"{GENERIC_WEB} v{web['policy_version']}")


def narrowed(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What a new version takes away: rights, allow-listed hosts, or retention."""
    lost = [r for r in RIGHTS if old[r] and not new[r]]
    lost += [f"host {h}" for h in old["hosts"] if h not in new["hosts"]]
    if old["retention_days"] and (new["retention_days"] or 0) < old["retention_days"]:
        lost.append("retention_days")
    return lost


def create_version(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    """Next immutable version of a family (PolicyVersionRequest), accepted by the administrator who creates it.
    When rights narrow, a dependency re-check is enqueued for the family's sources."""
    from app.errors import ApiError
    from app.jobs import queue

    def write(session: ClientSession) -> dict[str, Any]:
        previous = db[COLLECTION].find_one({"family": body["family"]}, sort=[("policy_version", -1)], session=session)
        doc = {
            "_id": new_id("pol"),
            "family": body["family"],
            "policy_version": (previous["policy_version"] + 1) if previous else 1,
            **{
                k: body[k]
                for k in (
                    *RIGHTS,
                    "attribution_required",
                    "retention_days",
                    "hosts",
                    "excluded_hosts",
                    "conditions",
                    "basis",
                    "expires_at",
                )
            },
            "status": "accepted",
            "effective_from": datetime.fromisoformat(body["effective_from"].replace("Z", "+00:00")),
            "accepted_on": utcnow().date().isoformat(),
            "accepted_by": f"{actor['role']} {actor['user_id']}",
        }
        if isinstance(doc["expires_at"], str):
            doc["expires_at"] = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00"))
        problems = contracts.errors(policy_view(doc), "sources.schema.json#/$defs/SourcePolicy")
        if problems:
            raise ApiError(
                422,
                "validation_failed",
                "The policy breaks the rights chain or the contract",
                fields=[{"path": p.split(": ", 1)[0], "message": p.split(": ", 1)[-1][:300]} for p in problems[:5]],
            )
        db[COLLECTION].insert_one(doc, session=session)
        lost = narrowed(previous, doc) if previous else []
        audit.record(
            db,
            "source_policy.created",
            "source_policy",
            doc["_id"],
            actor,
            details={
                "family": doc["family"],
                "policy_version": doc["policy_version"],
                "narrowed": ", ".join(lost) or "none",
            },
            session=session,
        )
        if lost:
            queue.enqueue(
                db,
                "invalidate_dependencies",
                f"invalidate_dependencies:policy:{doc['family']}:v{doc['policy_version']}",
                session=session,
            )
        return doc

    return policy_view(run_in_transaction(client, write))
