"""Checks over what collection actually stored (Step 05 acceptance; docs/06 rules). Read-only: each check reports
what it looked at and the records that break its rule, so the same checks can run on live data and in tests."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.db import utcnow
from app.sources import policies

FETCH_LOG_DAYS = 89  # the fetch log keeps 90 days (ai_fetch_log TTL); older pages cannot be matched to it


def _row(check: str, looked_at: int, broken: list[str]) -> dict[str, Any]:
    return {"check": check, "ok": not broken, "looked_at": looked_at, "broken": len(broken), "examples": broken[:5]}


def verify_collection(db: Database[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    sources = list(db["ai_sources"].find({}, {"author": 0}))
    by_key = {s["_id"]: s for s in sources}
    rows = []

    broken = []
    for s in sources:
        policy = policies.version(db, s["policy"])
        if policy is None or not policy["collection_allowed"]:
            broken.append(f"{s['_id']}: {s['policy']}")
    rows.append(_row("every source records a policy version that allowed its collection", len(sources), broken))

    web = [s for s in sources if s["connector_id"] == "web_fetch"]
    broken = []
    for s in web:
        policy = policies.version(db, s["policy"]) or {"hosts": [], "excluded_hosts": []}
        host = policies.host_of(s["canonical_url"])
        listed = any(host == h or host.endswith("." + h) for h in policy["hosts"])
        excluded = any(host == h or host.endswith("." + h) for h in policy.get("excluded_hosts", []))
        if not listed or excluded:
            broken.append(f"{s['_id']}: {host} under {s['policy']}")
    rows.append(_row("every web page's host is on its policy's allow-list", len(web), broken))

    recent = [s for s in web if s["collected_at"] >= utcnow() - timedelta(days=FETCH_LOG_DAYS)]
    broken = [
        s["_id"]
        for s in recent
        if db["ai_fetch_log"].count_documents(
            {"$or": [{"url": s["native_id"]}, {"final_url": s["native_id"]}], "outcome": "fetched"}
        )
        == 0
    ]
    rows.append(_row("every web page has its fetch decision logged", len(recent), broken))

    # robots.txt binds only under a policy version that obeys it; record_only versions log the verdict (D46).
    obeyed: dict[tuple[str, int], bool] = {}

    def obeys(family: str | None, version: int | None) -> bool:
        if family is None or version is None:
            return True
        if (family, version) not in obeyed:
            obeyed[(family, version)] = policies.obeys_robots(
                policies.version(db, {"family": family, "policy_version": version})
            )
        return obeyed[(family, version)]

    fetched = list(
        db["ai_fetch_log"].find({"outcome": "fetched"}, {"url": 1, "robots": 1, "family": 1, "policy_version": 1})
    )
    broken = [
        f"{f['url']}: {f['robots']}"
        for f in fetched
        if str(f.get("robots") or "").startswith("disallowed") and obeys(f.get("family"), f.get("policy_version"))
    ]
    rows.append(_row("nothing was fetched against robots.txt where the policy obeys it", len(fetched), broken))

    refused = set(db["ai_fetch_log"].distinct("host", {"robots": {"$regex": "robots_refused"}}))
    kept = [s for s in web if s["lifecycle"] not in ("withdrawn", "deleted", "expired")]
    broken = [
        s["_id"]
        for s in kept
        if policies.host_of(s["canonical_url"]) in refused
        and obeys(s["policy"]["family"], s["policy"]["policy_version"])
    ]
    rows.append(_row("no page kept from a site that refused us, where the policy obeys robots.txt", len(kept), broken))

    metadata = [s for s in sources if s["capture_level"] == "metadata_only"]
    broken = [
        s["_id"]
        for s in metadata
        if s.get("payload_ref") is not None or db["ai_payloads"].count_documents({"_id": s["_id"]})
    ]
    rows.append(_row("metadata-only records hold no text", len(metadata), broken))

    metadata_ids = {s["_id"] for s in metadata}
    evidence = list(db["ai_evidence"].find({}, {"source": 1}))
    broken = [e["_id"] for e in evidence if f"{e['source']['id']}@{e['source']['revision']}" in metadata_ids]
    rows.append(_row("no evidence comes from a metadata-only record", len(evidence), broken))

    videos = [s for s in sources if s["source_kind"] in ("video", "short")]
    broken = [
        s["_id"]
        for s in videos
        if s["capture_level"] != "metadata_only" and not (s.get("media") or {}).get("transcript_route")
    ]
    rows.append(_row("no video carries spoken content without a transcript route", len(videos), broken))

    comments = [s for s in sources if s["source_kind"] == "comment"]
    broken = [
        s["_id"]
        for s in comments
        if not s.get("parent") or f"{s['parent']['id']}@{s['parent']['revision']}" not in by_key
    ]
    rows.append(_row("every comment belongs to a stored parent", len(comments), broken))

    duplicates = list(
        db["ai_sources"].aggregate(
            [
                {"$group": {"_id": ["$connector_id", "$native_id", "$revision"], "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
            ]
        )
    )
    rows.append(_row("one record per source revision", len(sources), [str(d["_id"]) for d in duplicates]))

    windows = list(db["ai_connector_quota"].find())
    broken = [f"{w['_id']}: {w['used']}/{w['limit']}" for w in windows if w["used"] > w["limit"]]
    rows.append(_row("provider quotas were not exceeded", len(windows), broken))

    runs = list(db["ai_runs"].find({}, {"coverage": 1}))
    broken = []
    for run in runs:
        recorded = {c["connector_id"] for c in run["coverage"] if c["status"] != "access_pending"}
        used = set(db["ai_fetch_log"].distinct("connector_id", {"run_id": run["_id"]}))
        if used - recorded:
            broken.append(f"{run['_id']}: {', '.join(sorted(used - recorded))} used but not recorded as run")
    rows.append(_row("every connector a run used is in its coverage", len(runs), broken))

    places = {
        "ai_fetch_log": ["url"],
        "ai_connector_state": ["query_key", "cursor", "last_error.message"],
        "ai_sources": ["native_id", "canonical_url"],
        "ai_run_events": ["message"],
    }
    broken = []
    for secret in settings.secret_values():
        pattern = re.escape(secret)
        for collection, fields in places.items():
            if db[collection].count_documents({"$or": [{f: {"$regex": pattern}} for f in fields]}):
                broken.append(f"a configured secret appears in {collection}")
    rows.append(_row("no configured secret is stored in collected records", len(settings.secret_values()), broken))
    return rows
