#!/usr/bin/env python3
"""Generate contracts/v1/fixtures/*.json: synthetic, labelled contract fixtures.

    .venv/bin/python scripts/build_fixtures.py          # write fixtures
    .venv/bin/python scripts/build_fixtures.py --check  # exit 1 if any fixture file is stale

Every record describes the fictional projects "Fixture Towers" and "Sample Greens"
in "Example City" with .invalid URLs. Nothing here is real discussion or refers to
the five registered projects. Each case states the schema it targets, whether it
must be valid, why, and (for invalid cases) the error it must fail with.
Hashes are computed with the canonical method (D23), never typed by hand.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_tools as ct  # noqa: E402

FIXTURES = ct.FIXTURES
NOTE = "Synthetic fixture for contract tests. Fictional projects and sources; not evidence, never imported as real data."


def uid(prefix: str, n: int) -> str:
    return f"{prefix}_01JB{n:022d}"


def fake_sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def ts(day: int, hour: int = 10) -> str:
    return f"2026-09-{day:02d}T{hour:02d}:00:00Z"


P, P2 = uid("prj", 1), uid("prj", 2)
S_FORUM, S_VIDEO, S_REGISTRY, S_SEARCH = uid("src", 1), uid("src", 2), uid("src", 3), uid("src", 4)
L_VIDEO_P, L_VIDEO_P2, L_FORUM, L_REGISTRY = uid("lnk", 1), uid("lnk", 2), uid("lnk", 3), uid("lnk", 4)
E_FORUM, E_SPEECH, E_REGISTRY = uid("evd", 1), uid("evd", 2), uid("evd", 4)
C_OPINION, C_FACT = uid("clm", 1), uid("clm", 2)
F_DELAY, F_DATE = uid("fnd", 1), uid("fnd", 2)
R1, R2 = uid("rev", 1), uid("rev", 2)
D_APPROVE, D_LINK = uid("dec", 1), uid("dec", 2)
OP1, OP2 = uid("pub", 1), uid("pub", 2)
S_COMMENT, S_OTHER_POST = uid("src", 5), uid("src", 6)
L_COMMENT, L_OTHER_POST = uid("lnk", 5), uid("lnk", 6)
E_COMMENT, E_OTHER_POST = uid("evd", 5), uid("evd", 6)
REX_POST_ID, REX_COMMENT_ID, REX_FLAGGED_ID, REX_VIDEO_ID = uid("rex", 1), uid("rex", 2), uid("rex", 3), uid("rex", 4)
RERA = "FIX/0001/0001/2026/01"

MODERATOR = {"kind": "user", "user_id": uid("usr", 1), "role": "moderator"}
PUBLISHER = {"kind": "user", "user_id": uid("usr", 2), "role": "publisher"}
RESEARCHER = {"kind": "user", "user_id": uid("usr", 3), "role": "researcher"}
SYSTEM = {"kind": "system", "user_id": None, "role": None}
UNKNOWN_DATE = {"status": "unknown", "value": None, "precision": None, "basis": None}


def ref(id_: str, revision: int = 1) -> dict[str, Any]:
    return {"id": id_, "revision": revision}


def case(name: str, schema: str, instance: Any, why: str, tags: list[str] | None = None, error: str | None = None) -> dict[str, Any]:
    out = {"name": name, "schema": schema, "expect": "invalid" if error else "valid", "tags": tags or [], "why": why}
    if error:
        out["error_contains"] = error
    out["instance"] = instance
    return out


def variant(base: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    copied = copy.deepcopy(base)
    change(copied)
    return copied


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# --- Records -----------------------------------------------------------------------------

PROJECT = {
    "id": P,
    "slug": "fixture-towers-sector-0-example-city",
    "project_name": "Fixture Towers",
    "alternate_names": ["Fixture Twrs"],
    "locality": "Sector 0",
    "city": "Example City",
    "micromarket": "Example Micromarket",
    "developer": "Example Developer",
    "phase": None,
    "rera_registrations": [{"id": RERA, "id_normalised": RERA, "registered_name": "Fixture Towers Phase 1"}],
    "reference_url": None,
    "client_id": None,
    "client_ref": None,
    "input_schema_version": "1.1",
    "version": 1,
    "created_at": ts(20),
    "updated_at": ts(20),
}

CONFIG = {
    "project_id": P,
    "version": 3,
    "aliases": [
        {"text": "Fixture Towers", "normalised": "fixture towers", "target": {"kind": "project", "rera_id": None}, "mode": "standalone", "origin": "input_file", "proposal_id": None},
        {"text": "Fixture Towers Phase 1", "normalised": "fixture towers phase 1", "target": {"kind": "phase", "rera_id": RERA}, "mode": "standalone", "origin": "rera_registered_name", "proposal_id": None},
        {"text": "Towers", "normalised": "towers", "target": {"kind": "project", "rera_id": None}, "mode": "context_required", "origin": "approved_proposal", "proposal_id": uid("als", 2)},
    ],
    "construction_status": [
        {"status": "partially_ready", "applies_to": {"kind": "project", "rera_id": None}, "basis": "client_export", "as_of": "2026-09-25", "note": None},
        {"status": "ready_to_move", "applies_to": {"kind": "phase", "rera_id": RERA}, "basis": "rera_registry", "as_of": "2026-09-20", "note": "Phase 1 handed over per the registry"},
    ],
    "negative_keywords": ["Fixture Towers Otherville"],
    "input_languages": ["en", "hi", "hi-Latn"],
    "output_locale": "en-IN",
    "refresh": {"cadence": "daily_incremental_and_manual", "lookback_days": 90},
    "sources": [{"connector_id": "brave_search", "enabled": True}, {"connector_id": "youtube_data_api", "enabled": True}],
    "updated_at": ts(21),
    "updated_by": RESEARCHER,
}

ALIAS_PROPOSED = {
    "id": uid("als", 1),
    "project_id": P,
    "alias_text": "Fixture Twrs P1",
    "normalised": "fixture twrs p1",
    "alias_type": "short_name",
    "target": {"kind": "phase", "rera_id": RERA},
    "evidence_refs": [ref(E_FORUM)],
    "strong_identifier": {"kind": "rera_id", "evidence_ref": ref(E_FORUM)},
    "independent_origin_count": 2,
    "collision": {"status": "none", "colliding_project_ids": [], "reason": None},
    "status": "proposed",
    "decision": None,
    "proposed_by_task": uid("tsk", 1),
    "version": 0,
    "created_at": ts(22),
}

ALIAS_GENERIC_APPROVED = variant(
    ALIAS_PROPOSED,
    lambda a: a.update(
        id=uid("als", 2),
        alias_text="Towers",
        normalised="towers",
        target={"kind": "project", "rera_id": None},
        collision={"status": "generic", "colliding_project_ids": [], "reason": "A single common word"},
        status="approved",
        decision={"decision_id": uid("dec", 9), "mode": "context_required"},
        version=1,
    ),
)

POLICY_WEB = {
    "id": uid("pol", 1),
    "family": "web_public_pages",
    "policy_version": 2,
    "collection_allowed": True,
    "ai_processing_allowed": True,
    "quotation_allowed": True,
    "derived_publication_allowed": True,
    "attribution_required": True,
    "retention_days": 90,
    "hosts": [],
    "excluded_hosts": ["youtube.com", "reddit.com"],
    "conditions": ["Public pages only"],
    "robots_txt": "obey",
    "host_scope": "allow_list",
    "basis": "docs/06 scraping policy; verbatim review quotes with a credit line (D28)",
    "status": "accepted",
    "effective_from": ts(25),
    "expires_at": None,
    "accepted_on": "2026-09-28",
    "accepted_by": "Product owner (fixture)",
}

SOURCE_FORUM = {
    "id": S_FORUM,
    "revision": 1,
    "connector_id": "firecrawl",
    "native_id": "thread-123",
    "canonical_url": "https://forum.example.invalid/t/123",
    "source_kind": "forum_thread",
    "parent": None,
    "title": "Fixture Towers possession?",
    "author": {"display_name": None, "role": "unknown", "role_basis": "none"},
    "publication_date": UNKNOWN_DATE,
    "collected_at": ts(22),
    "language": "en",
    "capture_level": "full_content",
    "content_sha256": fake_sha("forum-thread-123"),
    "payload_ref": {"store": "payload_store", "key": "src/1/1"},
    "policy": {"family": "web_public_pages", "policy_version": 2},
    "lifecycle": "active",
    "media": None,
    "created_at": ts(22),
}

SOURCE_VIDEO = {
    **SOURCE_FORUM,
    "id": S_VIDEO,
    "connector_id": "youtube_data_api",
    "native_id": "video-abc",
    "canonical_url": "https://video.example.invalid/watch?v=abc",
    "source_kind": "video",
    "title": "Comparing Fixture Towers and Sample Greens",
    "author": {"display_name": "Example Creator", "role": "creator", "role_basis": "platform_badge"},
    "publication_date": {"status": "known", "value": ts(10), "precision": "day", "basis": "platform_metadata"},
    "language": "hi-Latn",
    "content_sha256": fake_sha("video-abc"),
    "payload_ref": {"store": "media_store", "key": "media/abc"},
    "policy": {"family": "youtube", "policy_version": 2},
    "media": {
        "duration_ms": 600000,
        "format": "unknown",
        "format_basis": "unknown",
        "access_status": "transcribed",
        "transcript_route": "creator_supplied",
        "channel": {"native_id": "channel-1", "title": "Example Creator"},
    },
}

SOURCE_REGISTRY = {
    **SOURCE_FORUM,
    "id": S_REGISTRY,
    "connector_id": "harera_registry",
    "native_id": RERA,
    "canonical_url": "https://registry.example.invalid/project/FIX-0001",
    "source_kind": "registration_record",
    "title": "Registry record for Fixture Towers Phase 1",
    "author": None,
    "publication_date": {"status": "known", "value": ts(1), "precision": "day", "basis": "registry_record"},
    "content_sha256": fake_sha("registry-FIX-0001"),
    "payload_ref": {"store": "payload_store", "key": "src/3/1"},
    "policy": {"family": "official_records", "policy_version": 1},
}

SOURCE_SEARCH = {
    **SOURCE_FORUM,
    "id": S_SEARCH,
    "connector_id": "brave_search",
    "native_id": "https://forum.example.invalid/t/123",
    "source_kind": "search_result",
    "capture_level": "metadata_only",
    "content_sha256": None,
    "payload_ref": None,
}


def link(id_: str, project: str, source: str, segment_key: str, anchor: Any, status: str, method: str, decided_by: str | None) -> dict[str, Any]:
    return {
        "id": id_,
        "project_id": project,
        "source": ref(source),
        "segment_key": segment_key,
        "segment_anchor": anchor,
        "status": status,
        "phase": {"rera_id": None, "certainty": "unknown"},
        "match": {
            "method": method,
            "rule_score": 870 if method == "deterministic" else None,
            "signals": ["project_name", "locality"],
            "matched_alias": None,
            "rationale": "Names the project and its locality",
        },
        "decided_by": decided_by,
        "superseded_by": [],
        "version": 1,
        "created_at": ts(22),
    }


def time_anchor(start: int, end: int) -> dict[str, Any]:
    return {"kind": "time", "start_ms": start, "end_ms": end, "precision": "approximate", "method": "transcript_segment"}


LINK_VIDEO_P = link(L_VIDEO_P, P, S_VIDEO, "t:0-240000", time_anchor(0, 240000), "accepted", "moderator", D_LINK)
LINK_VIDEO_P2 = link(L_VIDEO_P2, P2, S_VIDEO, "t:240000-600000", time_anchor(240000, 600000), "auto_accepted", "deterministic", None)
LINK_FORUM = link(L_FORUM, P, S_FORUM, "whole", None, "accepted", "deterministic", uid("dec", 3))
LINK_REGISTRY = link(L_REGISTRY, P, S_REGISTRY, "whole", None, "accepted", "deterministic", uid("dec", 4))

FORUM_TEXT = "I booked a 3 BHK here in 2024. The sample flat matched the brochure — but possession was delayed by six months."
FORUM_EXCERPT = FORUM_TEXT
FORUM_REVIEW_TEXT = "I booked a 3 BHK here in 2024. The sample flat matched the brochure, but possession was delayed by six months."
COMMENT_TEXT = "Site visit kiya tha pichle mahine. Construction bahut slow hai, do saal mein kuch nahi badla."
COMMENT_REVIEW_TEXT = "I visited the site last month. Construction is very slow, nothing has changed in two years."
OTHER_POST_TEXT = "I have been living here for a year and the maintenance is excellent."


def text_anchor(text: str, excerpt: str) -> dict[str, Any]:
    start = text.index(excerpt)
    return {
        "kind": "text",
        "representation": "original",
        "unit": "codepoint",
        "start": start,
        "end": start + len(excerpt),
        "excerpt_sha256": "sha256:" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }


EVIDENCE_FORUM = {
    "id": E_FORUM,
    "revision": 1,
    "project_id": P,
    "source": ref(S_FORUM),
    "link_id": L_FORUM,
    "anchor": text_anchor(FORUM_TEXT, FORUM_EXCERPT),
    "context_anchor": None,
    "excerpt_text": FORUM_EXCERPT,
    "excerpt_sha256": "sha256:" + hashlib.sha256(FORUM_EXCERPT.encode("utf-8")).hexdigest(),
    "language": "en",
    "modality": "text",
    "translation_of": None,
    "origin_cluster": {"id": uid("cls", 1), "version": 1},
    "policy": {"family": "web_public_pages", "policy_version": 2},
    "lifecycle": "active",
    "created_at": ts(22),
}

EVIDENCE_SPEECH = {
    **EVIDENCE_FORUM,
    "id": E_SPEECH,
    "source": ref(S_VIDEO),
    "link_id": L_VIDEO_P,
    "anchor": time_anchor(12000, 19000),
    "excerpt_text": "possession mein thoda delay hua",
    "excerpt_sha256": "sha256:" + hashlib.sha256("possession mein thoda delay hua".encode("utf-8")).hexdigest(),
    "language": "hi-Latn",
    "modality": "speech",
    "origin_cluster": {"id": uid("cls", 2), "version": 1},
    "policy": {"family": "youtube", "policy_version": 2},
}

REGISTRY_EXCERPT = "Proposed completion date: 31/12/2027"
EVIDENCE_REGISTRY = {
    **EVIDENCE_FORUM,
    "id": E_REGISTRY,
    "source": ref(S_REGISTRY),
    "link_id": L_REGISTRY,
    "anchor": text_anchor("Registration FIX-0001. " + REGISTRY_EXCERPT + ".", REGISTRY_EXCERPT),
    "excerpt_text": REGISTRY_EXCERPT,
    "excerpt_sha256": "sha256:" + hashlib.sha256(REGISTRY_EXCERPT.encode("utf-8")).hexdigest(),
    "origin_cluster": {"id": uid("cls", 3), "version": 1},
    "policy": {"family": "official_records", "policy_version": 1},
}

CLAIM_OPINION = {
    "id": C_OPINION,
    "revision": 1,
    "project_id": P,
    "aspect": "builder_reputation",
    "aspect_label": None,
    "claim_type": "opinion",
    "polarity": "negative",
    "perspective": "owner_awaiting_possession",
    "consistency_flags": [],
    "statement": "Buyers report that possession was delayed",
    "observation_time": UNKNOWN_DATE,
    "supporting_evidence": [ref(E_FORUM), ref(E_SPEECH)],
    "contradicting_evidence": [],
    "verification": {"status": "not_applicable", "primary_records": [], "checked_at": None, "reason": None},
    "origin_clusters": [uid("cls", n) for n in (1, 2, 5, 6, 7)],
    "independent_origin_count": 5,
    "confidence": {"value": None, "calibration_ref": None},
    "created_by_task": uid("tsk", 5),
    "created_at": ts(23),
}

CLAIM_FACT = {
    **CLAIM_OPINION,
    "id": C_FACT,
    "claim_type": "fact",
    "polarity": "neutral",
    "perspective": "official_record",
    "statement": "The registered completion date is 31 December 2027",
    "observation_time": {"status": "known", "value": ts(1), "precision": "day", "basis": "registry_record"},
    "supporting_evidence": [ref(E_REGISTRY)],
    "verification": {
        "status": "verified",
        "primary_records": [ref(E_REGISTRY)],
        "checked_at": ts(23),
        "reason": "Matches the registry record dated 1 Sep 2026",
    },
    "origin_clusters": [uid("cls", 3)],
    "independent_origin_count": 1,
}

FINDING_DELAY = {
    "id": F_DELAY,
    "revision": 1,
    "project_id": P,
    "kind": "con",
    "aspect": "builder_reputation",
    "wording": "Several buyers report that possession was delayed",
    "attribution": "reported_opinion",
    "claims": [ref(C_OPINION)],
    "caveats": ["Reported in public posts; not confirmed by the developer"],
    "origin_clusters": [uid("cls", n) for n in (1, 2, 5, 6, 7)],
    "independent_origin_count": 5,
    "review_status": "approved",
    "supersedes": None,
    "created_by": {"kind": "agent", "task_id": uid("tsk", 7), "actor": None},
    "created_at": ts(23),
}

FINDING_DATE = {
    **FINDING_DELAY,
    "id": F_DATE,
    "revision": 2,
    "kind": "neutral",
    "wording": "The registered completion date is 31 December 2027",
    "attribution": "verified_fact",
    "claims": [ref(C_FACT)],
    "caveats": [],
    "origin_clusters": [uid("cls", 3)],
    "independent_origin_count": 1,
    "supersedes": ref(F_DATE, 1),
    "created_by": {"kind": "moderator", "task_id": None, "actor": MODERATOR},
}


SOURCE_COMMENT = {
    **SOURCE_FORUM,
    "id": S_COMMENT,
    "connector_id": "youtube_data_api",
    "native_id": "comment-xyz",
    "canonical_url": "https://video.example.invalid/watch?v=abc&lc=xyz",
    "source_kind": "comment",
    "parent": ref(S_VIDEO),
    "title": None,
    "author": {"display_name": None, "role": "prospective_buyer", "role_basis": "self_described"},
    "publication_date": {"status": "known", "value": ts(15), "precision": "day", "basis": "platform_metadata"},
    "language": "hi-Latn",
    "content_sha256": fake_sha("comment-xyz"),
    "payload_ref": {"store": "payload_store", "key": "src/5/1"},
    "policy": {"family": "youtube", "policy_version": 2},
}
LINK_COMMENT = link(L_COMMENT, P, S_COMMENT, "whole", None, "accepted", "deterministic", uid("dec", 5))
EVIDENCE_COMMENT = {
    **EVIDENCE_FORUM,
    "id": E_COMMENT,
    "source": ref(S_COMMENT),
    "link_id": L_COMMENT,
    "anchor": text_anchor(COMMENT_TEXT, COMMENT_TEXT),
    "excerpt_text": COMMENT_TEXT,
    "excerpt_sha256": "sha256:" + hashlib.sha256(COMMENT_TEXT.encode("utf-8")).hexdigest(),
    "language": "hi-Latn",
    "origin_cluster": {"id": uid("cls", 8), "version": 1},
    "policy": {"family": "youtube", "policy_version": 2},
}

CLAIM_RESIDENT_FLAGGED = {
    **CLAIM_OPINION,
    "id": uid("clm", 3),
    "aspect": "maintenance_facility_mgmt",
    "polarity": "positive",
    "perspective": "resident_experience",
    "consistency_flags": ["status_unknown"],
    "statement": "The author says they have lived in the project for a year and praises maintenance",
    "supporting_evidence": [ref(E_OTHER_POST)],
    "origin_clusters": [uid("cls", 9)],
    "independent_origin_count": 1,
}


def review(
    id_: str,
    revision: int,
    source: str,
    link_id: str,
    evidence: list[str],
    source_kind: str,
    perspective: str,
    speaker: str,
    polarity: str,
    aspects: list[str],
    original: str,
    language: str,
    rendering: str,
    text: str,
    published: dict[str, Any],
    timestamp_ms: int | None,
    flags: list[str],
    status: str,
    supersedes: Any,
    created_by: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": id_,
        "revision": revision,
        "project_id": P,
        "source": ref(source),
        "link_id": link_id,
        "evidence": [ref(e) for e in evidence],
        "source_kind": source_kind,
        "perspective": perspective,
        "speaker_label": speaker,
        "polarity": polarity,
        "aspects": aspects,
        "original_text": original,
        "original_language": language,
        "rendering": rendering,
        "text": text,
        "published": published,
        "timestamp_ms": timestamp_ms,
        "consistency_flags": flags,
        "review_status": status,
        "supersedes": supersedes,
        "created_by": created_by,
        "policy": policy,
        "lifecycle": "active",
        "created_at": ts(24),
    }


BY_AGENT = {"kind": "agent", "task_id": uid("tsk", 11), "actor": None}
BY_MODERATOR = {"kind": "moderator", "task_id": None, "actor": MODERATOR}
WEB2 = {"family": "web_public_pages", "policy_version": 2}
YT2 = {"family": "youtube", "policy_version": 2}

REVIEW_POST = review(
    REX_POST_ID, 1, S_FORUM, L_FORUM, [E_FORUM], "forum_thread", "owner_awaiting_possession", "an_owner_awaiting_possession",
    "mixed", ["unit_layouts_livability", "builder_reputation"], FORUM_TEXT, "en", "punctuation_normalised", FORUM_REVIEW_TEXT, UNKNOWN_DATE, None, [],
    "approved", None, BY_AGENT, WEB2,
)
REVIEW_COMMENT = review(
    REX_COMMENT_ID, 2, S_COMMENT, L_COMMENT, [E_COMMENT], "comment", "site_visit", "a_site_visitor", "negative",
    ["builder_reputation"], COMMENT_TEXT, "hi-Latn", "translated", COMMENT_REVIEW_TEXT, SOURCE_COMMENT["publication_date"], None, [],
    "approved", ref(REX_COMMENT_ID, 1), BY_MODERATOR, YT2,
)
REVIEW_VIDEO = review(
    REX_VIDEO_ID, 1, S_VIDEO, L_VIDEO_P, [E_SPEECH], "video", "third_party_report", "a_video_creator", "negative",
    ["builder_reputation"], "possession mein thoda delay hua", "hi-Latn", "translated", "Possession has been delayed a little.",
    SOURCE_VIDEO["publication_date"], 12000, [], "approved", None, BY_AGENT, YT2,
)
REVIEW_FLAGGED = review(
    REX_FLAGGED_ID, 1, S_OTHER_POST, L_OTHER_POST, [E_OTHER_POST], "forum_post", "resident_experience", "a_resident", "positive",
    ["maintenance_facility_mgmt"], OTHER_POST_TEXT, "en", "verbatim", OTHER_POST_TEXT, UNKNOWN_DATE, None, ["status_unknown"],
    "pending", None, BY_AGENT, WEB2,
)


def public_review(rex: dict[str, Any], platform: str, kind: str) -> dict[str, Any]:
    return {
        "text": rex["text"],
        "polarity": rex["polarity"],
        "aspects": rex["aspects"],
        "credit": {
            "speaker_label": rex["speaker_label"],
            "platform": platform,
            "kind": kind,
            "published": rex["published"],
            "timestamp_ms": rex["timestamp_ms"],
            "translated_from": rex["original_language"] if rex["rendering"] == "translated" else None,
        },
        "source_url": None,
        "support": {"review": ref(rex["id"], rex["revision"]), "source": rex["source"], "evidence": rex["evidence"]},
    }


def support(findings: list[dict[str, Any]], claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {"findings": findings, "claims": claims}


PAYLOAD = {
    "payload_schema": "content-payload/1",
    "project": {"id": P, "slug": PROJECT["slug"], "name": "Fixture Towers"},
    "locale": "en-IN",
    "evidence_window": {"from": "2026-06-27", "to": "2026-09-25"},
    "heading": "What buyers discuss about Fixture Towers",
    "overview": {
        "text": "Public discussion of Fixture Towers mostly concerns possession timing. The registry lists a completion date of 31 December 2027.",
        "support": support([ref(F_DELAY), ref(F_DATE, 2)], [ref(C_OPINION), ref(C_FACT)]),
    },
    "advantages": [],
    "considerations": [
        {
            "text": "Several buyers report that possession was delayed.",
            "caveat": "Reported in public posts; not confirmed by the developer.",
            "support": support([ref(F_DELAY)], [ref(C_OPINION)]),
        }
    ],
    "reviews": [
        public_review(REVIEW_POST, "Example forum", "post"),
        public_review(REVIEW_COMMENT, "Example video site", "comment"),
        public_review(REVIEW_VIDEO, "Example video site", "video"),
    ],
    "questions": [
        {
            "question": "What is the registered completion date?",
            "answer": "The RERA registry lists 31 December 2027.",
            "support": support([ref(F_DATE, 2)], [ref(C_FACT)]),
        }
    ],
    "sources": [
        {"source": ref(S_FORUM), "title": "Fixture Towers possession?", "url": SOURCE_FORUM["canonical_url"], "platform": "Example forum", "published": UNKNOWN_DATE, "timestamp_ms": None},
        {"source": ref(S_VIDEO), "title": "Comparing Fixture Towers and Sample Greens", "url": SOURCE_VIDEO["canonical_url"], "platform": "Example video site", "published": SOURCE_VIDEO["publication_date"], "timestamp_ms": 12000},
        {"source": ref(S_REGISTRY), "title": "Registry record", "url": SOURCE_REGISTRY["canonical_url"], "platform": "RERA registry", "published": SOURCE_REGISTRY["publication_date"], "timestamp_ms": None},
    ],
    "coverage_note": "Based on 6 public discussions and 1 registry record collected between 27 Jun and 25 Sep 2026. Not a survey of all buyers.",
    "reviewed_on": "2026-09-25",
    "attribution": "Compiled by the editorial team from public discussions and official records; reviewed by our editorial team.",
    "metadata": {
        "title": "Fixture Towers: what buyers discuss",
        "description": "Evidence-linked summary of public discussion about Fixture Towers, Sector 0, Example City.",
        "canonical_path": "/projects/fixture-towers-sector-0-example-city",
        "robots": "noindex",
    },
    "json_ld": {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "What buyers discuss about Fixture Towers",
        "dateModified": "2026-09-25",
        "about": {"@type": "Place", "name": "Fixture Towers, Sector 0, Example City"},
    },
}

MANIFEST = {
    "findings": [ref(F_DELAY), ref(F_DATE, 2)],
    "claims": [ref(C_OPINION), ref(C_FACT)],
    "reviews": [ref(REX_POST_ID), ref(REX_COMMENT_ID, 2), ref(REX_VIDEO_ID)],
    "evidence": [ref(E_FORUM), ref(E_SPEECH), ref(E_REGISTRY), ref(E_COMMENT)],
    "sources": [ref(S_FORUM), ref(S_VIDEO), ref(S_REGISTRY), ref(S_COMMENT)],
    "links": sorted([L_VIDEO_P, L_FORUM, L_REGISTRY, L_COMMENT]),
    "policies": [
        {"family": "official_records", "policy_version": 1},
        {"family": "web_public_pages", "policy_version": 2},
        {"family": "youtube", "policy_version": 2},
    ],
    "eligibility_epoch": 3,
}


def content_revision(id_: str, revision: int, payload: dict[str, Any], lifecycle: str, supersedes: Any, created_by: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": id_,
        "project_id": P,
        "locale": "en-IN",
        "revision": revision,
        "payload": payload,
        "payload_sha256": ct.content_hash(payload),
        "manifest": MANIFEST,
        "manifest_sha256": ct.content_hash(MANIFEST),
        "lifecycle": lifecycle,
        "supersedes": supersedes,
        "created_by": created_by,
        "qa": {"status": "passed", "blocking_issues": 0, "nonblocking_issues": 1, "report_task": uid("tsk", 9)},
        "created_at": ts(24),
    }


REV1 = content_revision(R1, 1, PAYLOAD, "approved", None, {"kind": "agent", "task_id": uid("tsk", 8), "actor": None})
PAYLOAD_EDITED = variant(PAYLOAD, lambda p: p["considerations"][0].update(text="Several buyers report that possession was delayed by about six months."))
REV2 = content_revision(R2, 2, PAYLOAD_EDITED, "final_review", ref(R1), {"kind": "moderator", "task_id": None, "actor": MODERATOR})

APPROVAL = {
    "id": D_APPROVE,
    "target": {"type": "content_revision", "id": R1, "revision": 1},
    "action": "approve",
    "reason": None,
    "actor": MODERATOR,
    "binding": {
        "project_id": P,
        "locale": "en-IN",
        "payload_sha256": REV1["payload_sha256"],
        "manifest_sha256": REV1["manifest_sha256"],
        "eligibility_epoch": 3,
        "expected_state_version": 7,
    },
    "idempotency_key": "approve-rev1-0001",
    "request_id": "req-0001",
    "created_at": ts(24, 12),
}


def pointer(rev: dict[str, Any]) -> dict[str, Any]:
    return {"revision_id": rev["id"], "revision": rev["revision"], "payload_sha256": rev["payload_sha256"], "manifest_sha256": rev["manifest_sha256"]}


STATE_ACTIVE = {
    "project_id": P,
    "locale": "en-IN",
    "version": 8,
    "approved": {**pointer(REV1), "decision_id": D_APPROVE},
    "active": {**pointer(REV1), "operation_id": OP1, "activated_at": ts(24, 13)},
    "serving_state": "active",
    "eligibility_epoch": 3,
    "pending_invalidation": False,
    "pending_intent": None,
    "updated_at": ts(24, 13),
}

STATE_EMPTY = {**STATE_ACTIVE, "version": 0, "approved": None, "active": None, "serving_state": "unpublished", "eligibility_epoch": 0, "updated_at": ts(20)}

STATE_DISABLED = {
    **STATE_ACTIVE,
    "version": 9,
    "serving_state": "temporarily_disabled",
    "eligibility_epoch": 4,
    "pending_invalidation": True,
    "pending_intent": {"operation_id": OP2, "kind": "revalidate_after_invalidation", "created_at": ts(26)},
    "updated_at": ts(26),
}

OPERATION_VERIFIED = {
    "id": OP1,
    "kind": "publish",
    "project_id": P,
    "locale": "en-IN",
    "target": pointer(REV1),
    "expected_state_version": 7,
    "idempotency_key": "publish-rev1-0001",
    "request_digest": fake_sha("publish-rev1-request"),
    "actor": PUBLISHER,
    "reason": None,
    "status": "verified",
    "attempts": 1,
    "revalidation": {"requested_at": ts(24, 13), "acknowledged_at": ts(24, 13), "http_status": 200},
    "verification": {"verified_at": ts(24, 14), "rendered_revision_id": R1, "rendered_payload_sha256": REV1["payload_sha256"]},
    "error": None,
    "rolled_back_by": None,
    "created_at": ts(24, 13),
    "activated_at": ts(24, 13),
}

OPERATION_UNPUBLISH = {
    **OPERATION_VERIFIED,
    "id": OP2,
    "kind": "unpublish",
    "target": None,
    "idempotency_key": "unpublish-0001",
    "request_digest": fake_sha("unpublish-request"),
    "reason": "Project details under review",
    "verification": {"verified_at": ts(26, 12), "rendered_revision_id": None, "rendered_payload_sha256": None},
}

COVERAGE = [
    {"connector_id": "brave_search", "status": "complete_for_query", "attempted_queries": 6, "fetched": 14, "matched": 3, "analysed": 3, "metadata_only": 11, "last_success_at": ts(25), "note": None},
    {"connector_id": "youtube_data_api", "status": "partial", "attempted_queries": 4, "fetched": 2, "matched": 1, "analysed": 0, "metadata_only": 1, "last_success_at": ts(25), "note": "Quota exhausted on the second page"},
    {"connector_id": "reddit_api", "status": "access_pending", "attempted_queries": 0, "fetched": 0, "matched": 0, "analysed": 0, "metadata_only": 0, "last_success_at": None, "note": "No demonstrated credential"},
]

RUN_INSUFFICIENT = {
    "id": uid("run", 1),
    "project_id": P2,
    "stage": "insufficient_evidence",
    "trigger": "manual",
    "requested_by": RESEARCHER,
    "window": {"from": "2026-06-27T00:00:00Z", "to": "2026-09-25T00:00:00Z"},
    "coverage": COVERAGE,
    "budget": {"max_usd": 5, "spent_usd": 0.42, "exhausted": False},
    "content_revision_id": None,
    "outcome_note": "No eligible evidence supported a finding",
    "created_at": ts(25),
    "updated_at": ts(25, 11),
}

JOB_RUNNING = {
    "id": uid("job", 1),
    "logical_key": f"collect:{P}:2026-09-25",
    "kind": "collect",
    "run_id": uid("run", 2),
    "project_id": P,
    "status": "running",
    "attempts": 1,
    "max_attempts": 5,
    "next_attempt_at": None,
    "lease": {"owner": "worker-1", "expires_at": ts(25, 11), "fencing_token": 4},
    "deadline": ts(25, 18),
    "checkpoint_id": "ckpt-1",
    "error": None,
    "created_at": ts(25),
    "updated_at": ts(25, 10),
}


def agent_run(agent: str, model: str | None) -> dict[str, Any]:
    return {
        "task_id": uid("tsk", 20),
        "run_id": uid("run", 2),
        "project_id": P,
        "agent": agent,
        "outcome": "completed",
        "input_refs": [ref(E_FORUM)],
        "output_refs": [ref(C_OPINION)],
        "prompt_version": "claim_extractor.1.0",
        "schema_version": "1.0.0",
        "requested_model": model,
        "returned_model": model,
        "stop_reason": "end_turn" if model else None,
        "tool_steps": 0,
        "attempt": 1,
        "repair_used": False,
        "usage": {"input_tokens": 1800 if model else None, "output_tokens": 240 if model else None, "cache_read_input_tokens": None, "audio_seconds": None},
        "estimated_cost_usd": None,
        "provider_request_id": None,
        "elapsed_ms": 2100,
        "error": None,
        "created_at": ts(25),
    }


DELETION_DONE = {
    "id": uid("del", 1),
    "scope": {"kind": "source_revision", "source": ref(S_FORUM), "policy": None},
    "reason": "Author asked for removal",
    "requested_by": MODERATOR,
    "status": "completed",
    "affected": {"projects": [P], "evidence": 1, "claims": 1, "findings": 1, "content_revisions": [R1]},
    "invalidated_at": ts(26, 10),
    "erased_at": ts(26, 11),
    "created_at": ts(26, 9),
}

CORRECTION = {
    "id": uid("cor", 1),
    "project_id": P,
    "locale": "en-IN",
    "revision_id": R1,
    "message": "The completion date was revised last week.",
    "contact": None,
    "status": "received",
    "decision_id": None,
    "created_at": ts(26),
}

SYNTHESIS_EMPTY = {"outcome": "insufficient_evidence", "findings": [], "insufficiency_note": "Only one promotional source mentions the project"}

IDENTITY = {
    "outcome": "needs_review",
    "segments": [
        {
            "segment_key": "whole",
            "decision": "ambiguous",
            "project_id": None,
            "phase_rera_id": None,
            "signals": ["project_name"],
            "matched_alias": None,
            "rationale": "The same name is used for a project in another city",
        }
    ],
    "alias_proposals": [
        {
            "alias_text": "Fixture Twrs",
            "alias_type": "spelling_variant",
            "target_rera_id": None,
            "evidence_ids": [E_FORUM],
            "strong_identifier_kind": "developer_and_locality",
            "strong_identifier_evidence_id": E_FORUM,
        }
    ],
    "uncertainty_reasons": ["No locality in the post title"],
}

CLAIMS_OUT = {
    "outcome": "completed",
    "claims": [
        {
            "aspect": "builder_reputation",
            "aspect_label": None,
            "claim_type": "opinion",
            "polarity": "negative",
            "perspective": "owner_awaiting_possession",
            "statement": "Possession was delayed",
            "evidence_ids": [E_FORUM],
            "observation_date_status": "unknown",
            "observation_date": None,
        }
    ],
}


def fixture_cases() -> dict[str, list[dict[str, Any]]]:
    cat = "catalogue.schema.json#/$defs/"
    src = "sources.schema.json#/$defs/"
    evd = "evidence.schema.json#/$defs/"
    con = "content.schema.json#/$defs/"
    pub = "publication.schema.json#/$defs/"
    ops = "operations.schema.json#/$defs/"
    agt = "agents.schema.json#/$defs/"
    api = "api.schema.json#/$defs/"
    return {
        "catalogue": [
            case("project", cat + "Project", PROJECT, "Catalogue record with a phase registration"),
            case("project_config", cat + "ProjectConfig", CONFIG, "Aliases from the input file, a RERA name and an approved proposal"),
            case("alias_proposed", cat + "AliasProposal", ALIAS_PROPOSED, "Proposal cites a span with a strong identifier; no decision yet", ["alias_review"]),
            case("alias_generic_context_required", cat + "AliasProposal", ALIAS_GENERIC_APPROVED, "A generic alias approved only as context-required", ["alias_review"]),
            case(
                "alias_generic_standalone",
                cat + "AliasProposal",
                variant(ALIAS_GENERIC_APPROVED, lambda a: a["decision"].update(mode="standalone")),
                "A generic alias cannot be approved as standalone (D17)",
                ["alias_review"],
                "'context_required' was expected",
            ),
            case(
                "alias_proposed_with_decision",
                cat + "AliasProposal",
                variant(ALIAS_PROPOSED, lambda a: a.update(decision={"decision_id": uid("dec", 9), "mode": None})),
                "A proposal has no decision until someone decides",
                [],
                "is not of type 'null'",
            ),
            case(
                "alias_target_phase_without_rera",
                cat + "AliasTarget",
                {"kind": "phase", "rera_id": None},
                "A phase alias must name its registration",
                [],
                "None is not of type 'string'",
            ),
            case(
                "input_placeholder",
                cat + "ProjectInput",
                {"project_name": "<Project 1 name>", "locality": "Sector 0", "city": "Example City"},
                "Template placeholders are rejected",
                [],
                "does not match",
            ),
            case(
                "config_unknown_construction_status",
                cat + "ProjectConfig",
                variant(CONFIG, lambda c: c["construction_status"][0].update(status="coming_soon")),
                "Only the four construction statuses exist (D27)",
                ["status_consistency"],
                "'coming_soon' is not one of",
            ),
        ],
        "sources": [
            case("policy_web_accepted", src + "SourcePolicy", POLICY_WEB, "Accepted policy with its approver"),
            case(
                "policy_ai_without_collection",
                src + "SourcePolicy",
                variant(POLICY_WEB, lambda p: p.update(collection_allowed=False, retention_days=None)),
                "AI processing needs collection rights",
                ["policy_chain"],
                "True was expected",
            ),
            case(
                "policy_accepted_without_approver",
                src + "SourcePolicy",
                variant(POLICY_WEB, lambda p: p.update(accepted_by=None)),
                "An accepted policy records who accepted it",
                ["policy_chain"],
                "None is not of type 'string'",
            ),
            case("source_unknown_date", src + "SourceRevision", SOURCE_FORUM, "Publication date unknown and stored as unknown", ["unknown_date"]),
            case(
                "source_unknown_date_with_collection_time",
                src + "SourceRevision",
                variant(SOURCE_FORUM, lambda s: s["publication_date"].update(value=ts(22))),
                "Collection time must never stand in for an unknown publication date",
                ["unknown_date"],
                "is not of type 'null'",
            ),
            case("source_video_unknown_format", src + "SourceRevision", SOURCE_VIDEO, "Video whose format is unknown", ["multi_project_video"]),
            case(
                "source_short_from_duration",
                src + "SourceRevision",
                variant(SOURCE_VIDEO, lambda s: s["media"].update(duration_ms=45000, format="short", format_basis="unknown")),
                "Duration alone never establishes Shorts format",
                ["shorts_format"],
                "is not one of ['platform_metadata', 'url_pattern']",
            ),
            case("source_search_metadata_only", src + "SourceRevision", SOURCE_SEARCH, "A search hit is discovery metadata only", ["metadata_not_evidence"]),
            case(
                "source_search_full_content",
                src + "SourceRevision",
                variant(SOURCE_SEARCH, lambda s: s.update(capture_level="full_content", content_sha256=fake_sha("x"))),
                "A search hit can never carry content",
                ["metadata_not_evidence"],
                "'metadata_only' was expected",
            ),
            case("link_video_project_one", src + "ProjectSourceLink", LINK_VIDEO_P, "First segment of a comparison video, linked to Fixture Towers", ["multi_project_video"]),
            case("link_video_project_two", src + "ProjectSourceLink", LINK_VIDEO_P2, "Second segment of the same video revision, linked to Sample Greens", ["multi_project_video"]),
            case(
                "link_rejected_by_rule",
                src + "ProjectSourceLink",
                variant(LINK_VIDEO_P2, lambda l: l.update(status="rejected")),
                "The matching rules can create a link as rejected (same name in another city); no moderator decided it (D45)",
            ),
            case(
                "link_whole_with_anchor",
                src + "ProjectSourceLink",
                variant(LINK_FORUM, lambda l: l.update(segment_anchor=time_anchor(0, 1000))),
                "A whole-source link has no segment anchor",
                [],
                "is not of type 'null'",
            ),
            case(
                "link_accepted_without_decision",
                src + "ProjectSourceLink",
                variant(LINK_VIDEO_P, lambda l: l.update(decided_by=None)),
                "An accepted link names the decision that accepted it",
                [],
                "None is not of type 'string'",
            ),
            case(
                "media_segment_speech",
                src + "MediaSegment",
                {
                    "id": uid("seg", 1),
                    "source": ref(S_VIDEO),
                    "segment_key": "t:0-240000",
                    "time": time_anchor(0, 240000),
                    "language": "hi-Latn",
                    "modality": "speech",
                    "transcription": {"engine": "faster-whisper", "model_size": "small", "language_hint": "hi", "caption_kind": None},
                    "original_text_ref": "seg/1/original",
                    "translation": {"language": "en", "text_ref": "seg/1/en", "method": "language_agent"},
                    "quality_flags": ["code_switching"],
                },
                "Speech segment with transcription method and separate translation",
                ["multi_project_video"],
            ),
            case(
                "media_segment_from_captions",
                src + "MediaSegment",
                {
                    "id": uid("seg", 2),
                    "source": ref(S_VIDEO),
                    "segment_key": "t:0-240000",
                    "time": time_anchor(0, 240000),
                    "language": "hi-Latn",
                    "modality": "speech",
                    "transcription": {"engine": "platform_captions", "model_size": None, "language_hint": None, "caption_kind": "auto_generated"},
                    "original_text_ref": "seg/1/original",
                    "translation": {"language": "en", "text_ref": "seg/1/en", "method": "language_agent"},
                    "quality_flags": ["auto_generated_captions"],
                },
                "Speech from the platform caption track: no Whisper model, the caption kind recorded (D47)",
                ["multi_project_video"],
            ),
            case(
                "media_segment_captions_with_model",
                src + "MediaSegment",
                {
                    "id": uid("seg", 3),
                    "source": ref(S_VIDEO),
                    "segment_key": "t:0-240000",
                    "time": time_anchor(0, 240000),
                    "language": "hi-Latn",
                    "modality": "speech",
                    "transcription": {"engine": "platform_captions", "model_size": "small", "language_hint": None, "caption_kind": "manual"},
                    "original_text_ref": "seg/1/original",
                    "translation": {"language": "en", "text_ref": "seg/1/en", "method": "language_agent"},
                    "quality_flags": ["code_switching"],
                },
                "Captions are not a Whisper run, so they name no model size",
                [],
                "is not of type 'null'",
            ),
            case(
                "media_segment_on_screen_text",
                src + "MediaSegment",
                {
                    "id": uid("seg", 4),
                    "source": ref(S_VIDEO),
                    "segment_key": "f:120000:text",
                    "time": {"kind": "time", "start_ms": 120000, "end_ms": 120001, "precision": "exact", "method": "frame_sample"},
                    "language": "en",
                    "modality": "on_screen_text",
                    "transcription": None,
                    "original_text_ref": "seg/4/original",
                    "translation": None,
                    "quality_flags": ["possible_render", "numbers_uncertain"],
                },
                "Text read from one sampled frame of a render: kept verbatim, flagged so it never proves construction (D49)",
            ),
            case(
                "media_segment_frame_claims_transcription",
                src + "MediaSegment",
                {
                    "id": uid("seg", 5),
                    "source": ref(S_VIDEO),
                    "segment_key": "f:120000:scene",
                    "time": {"kind": "time", "start_ms": 120000, "end_ms": 120001, "precision": "exact", "method": "frame_sample"},
                    "language": "en",
                    "modality": "frame",
                    "transcription": {"engine": "faster-whisper", "model_size": "small", "language_hint": None, "caption_kind": None},
                    "original_text_ref": "seg/5/original",
                    "translation": None,
                    "quality_flags": [],
                },
                "A frame description is not transcribed speech",
                [],
                "is not of type 'null'",
            ),
        ],
        "evidence": [
            case("evidence_text", evd + "Evidence", EVIDENCE_FORUM, "Text evidence anchored in code points"),
            case("evidence_speech_segment", evd + "Evidence", EVIDENCE_SPEECH, "Speech evidence from the Fixture Towers segment of a comparison video", ["multi_project_video"]),
            case(
                "evidence_from_metadata",
                evd + "Evidence",
                variant(EVIDENCE_FORUM, lambda e: e.update(modality="metadata")),
                "Metadata is never evidence",
                ["metadata_not_evidence"],
                "should not be valid",
            ),
            case(
                "evidence_speech_with_text_anchor",
                evd + "Evidence",
                variant(EVIDENCE_SPEECH, lambda e: e.update(anchor=EVIDENCE_FORUM["anchor"])),
                "Speech evidence is anchored in time",
                [],
                "'time' was expected",
            ),
            case(
                "evidence_withdrawn_erased",
                evd + "Evidence",
                variant(EVIDENCE_FORUM, lambda e: e.update(lifecycle="withdrawn", excerpt_text=None)),
                "Withdrawn evidence keeps audit metadata only",
                ["withdrawal"],
            ),
            case(
                "evidence_withdrawn_with_text",
                evd + "Evidence",
                variant(EVIDENCE_FORUM, lambda e: e.update(lifecycle="withdrawn")),
                "Withdrawn evidence cannot keep its excerpt",
                ["withdrawal"],
                "is not of type 'null'",
            ),
            case("claim_opinion_many_origins", evd + "Claim", CLAIM_OPINION, "Five independent origins still leave an opinion unverified", ["independent_counts_not_truth"]),
            case("claim_fact_verified", evd + "Claim", CLAIM_FACT, "A fact verified against a dated primary record"),
            case(
                "claim_verified_by_count",
                evd + "Claim",
                variant(CLAIM_FACT, lambda c: c.update(independent_origin_count=7) or c["verification"].update(primary_records=[])),
                "Seven posts saying the same thing do not verify a fact",
                ["independent_counts_not_truth"],
                "should be non-empty",
            ),
            case(
                "claim_opinion_verified",
                evd + "Claim",
                variant(CLAIM_OPINION, lambda c: c["verification"].update(status="verified", primary_records=[ref(E_REGISTRY)], checked_at=ts(23), reason="x")),
                "Opinions are attributed, never verified",
                ["independent_counts_not_truth"],
                "'not_applicable' was expected",
            ),
            case(
                "claim_uncalibrated_confidence",
                evd + "Claim",
                variant(CLAIM_OPINION, lambda c: c.update(confidence={"value": 0.8, "calibration_ref": None})),
                "A confidence value needs the evaluation that calibrated it",
                ["calibrated_confidence"],
                "None is not of type 'string'",
            ),
            case("finding_con", evd + "Finding", FINDING_DELAY, "Con finding built from an exact claim revision"),
            case("finding_revision_two", evd + "Finding", FINDING_DATE, "Moderator edit saved as revision 2"),
            case(
                "finding_revision_two_without_base",
                evd + "Finding",
                variant(FINDING_DATE, lambda f: f.update(supersedes=None)),
                "A later revision names the revision it replaces",
                [],
                "None is not of type 'object'",
            ),
            case("claim_resident_flagged", evd + "Claim", CLAIM_RESIDENT_FLAGGED, "A 'lived here' claim with no identified ready phase is flagged, not used", ["status_consistency"]),
            case("source_comment", src + "SourceRevision", SOURCE_COMMENT, "A YouTube comment is its own text source under its video", ["video_reviews"]),
            case("evidence_comment", evd + "Evidence", EVIDENCE_COMMENT, "A Hinglish comment kept in its original words"),
            case("review_post_normalised", evd + "ReviewExcerpt", REVIEW_POST, "A buyer's post with only a dash changed to a comma", ["source_reviews"]),
            case("review_comment_translated", evd + "ReviewExcerpt", REVIEW_COMMENT, "A Hinglish YouTube comment translated, revision 2 after a moderator fix", ["source_reviews", "video_reviews"]),
            case("review_video_spoken", evd + "ReviewExcerpt", REVIEW_VIDEO, "A spoken review from an authorised transcript, with its timestamp", ["source_reviews", "video_reviews"]),
            case("review_flagged_pending", evd + "ReviewExcerpt", REVIEW_FLAGGED, "A 'lived here' post in a partly ready project with no phase named waits for a moderator", ["source_reviews", "status_consistency"]),
            case(
                "review_flagged_approved",
                evd + "ReviewExcerpt",
                variant(REVIEW_FLAGGED, lambda r: r.update(review_status="approved")),
                "A flagged review cannot be approved (D27)",
                ["status_consistency"],
                "is expected to be empty",
            ),
            case(
                "review_english_marked_translated",
                evd + "ReviewExcerpt",
                variant(REVIEW_POST, lambda r: r.update(rendering="translated")),
                "Only non-English originals are translated",
                ["source_reviews"],
                "should not be valid",
            ),
            case(
                "review_withdrawn_keeps_words",
                evd + "ReviewExcerpt",
                variant(REVIEW_POST, lambda r: r.update(lifecycle="withdrawn")),
                "A withdrawn source's words are erased from its review",
                ["withdrawal"],
                "is not of type 'null'",
            ),
            case(
                "review_neutral",
                evd + "ReviewExcerpt",
                variant(REVIEW_POST, lambda r: r.update(polarity="neutral")),
                "Reviews are positive, negative or mixed",
                ["source_reviews"],
                "should not be valid",
            ),
            case(
                "review_from_search_result",
                evd + "ReviewExcerpt",
                variant(REVIEW_POST, lambda r: r.update(source_kind="search_result")),
                "A search snippet is not anyone's review",
                ["source_reviews"],
                "'search_result' is not one of",
            ),
            case(
                "review_video_without_timestamp",
                evd + "ReviewExcerpt",
                variant(REVIEW_VIDEO, lambda r: r.update(timestamp_ms=None)),
                "A spoken review points to its moment in the video",
                ["video_reviews"],
                "None is not of type 'integer'",
            ),
        ],
        "content": [
            case("content_revision_approved", con + "ContentRevision", REV1, "Approved revision with no advantages and one consideration", ["unequal_lists"]),
            case("content_revision_edited", con + "ContentRevision", REV2, "A one-sentence edit is a new revision with a new hash", ["stale_approval_rejected"]),
            case(
                "payload_block_without_support",
                con + "ContentPayload",
                variant(PAYLOAD, lambda p: p["considerations"][0]["support"].update(findings=[])),
                "Every substantive block cites exact findings",
                ["every_block_supported"],
                "should be non-empty",
            ),
            case(
                "payload_with_rating",
                con + "ContentPayload",
                variant(PAYLOAD, lambda p: p["json_ld"].update(aggregateRating={"@type": "AggregateRating", "ratingValue": 4})),
                "No aggregate ratings from scraped sentiment",
                ["no_ratings"],
                "should not be valid",
            ),
            case(
                "payload_with_decimal",
                con + "ContentPayload",
                variant(PAYLOAD, lambda p: p["json_ld"].update(ratingHint=4.5)),
                "Hashed content allows integers only",
                ["integers_only"],
                "4.5 is not of type 'integer'",
            ),
            case(
                "revision_final_review_with_blocking_qa",
                con + "ContentRevision",
                variant(REV2, lambda r: r["qa"].update(status="issues_found", blocking_issues=2)),
                "Blocking QA issues keep a revision out of final review",
                [],
                "0 was expected",
            ),
            case("decision_final_approval", con + "ReviewDecision", APPROVAL, "Final approval bound to exact hashes, epoch and state version", ["approval_binding"]),
            case(
                "decision_approval_without_binding",
                con + "ReviewDecision",
                variant(APPROVAL, lambda d: d.update(binding=None)),
                "A final approval must be bound to exact hashes",
                ["approval_binding"],
                "None is not of type 'object'",
            ),
            case(
                "decision_by_system",
                con + "ReviewDecision",
                variant(APPROVAL, lambda d: d.update(actor=SYSTEM)),
                "Only a person can approve; models and services cannot",
                ["no_self_approval"],
                "'user' was expected",
            ),
            case(
                "decision_reject_without_reason",
                con + "ReviewDecision",
                variant(APPROVAL, lambda d: d.update(action="reject", binding=None)),
                "A rejection needs a reason",
                [],
                "None is not of type 'string'",
            ),
        ],
        "publication": [
            case("state_unpublished", pub + "PublicationState", STATE_EMPTY, "Nothing approved or active yet"),
            case("state_active", pub + "PublicationState", STATE_ACTIVE, "Approved and active revision 1"),
            case("state_disabled_after_withdrawal", pub + "PublicationState", STATE_DISABLED, "Invalidation pending: serving disabled, epoch bumped", ["withdrawal"]),
            case(
                "state_serving_during_invalidation",
                pub + "PublicationState",
                variant(STATE_DISABLED, lambda s: s.update(serving_state="active")),
                "Serving fails closed while an invalidation is pending",
                ["withdrawal"],
                "is not one of ['temporarily_disabled', 'unpublished']",
            ),
            case(
                "state_active_without_pointer",
                pub + "PublicationState",
                variant(STATE_ACTIVE, lambda s: s.update(active=None)),
                "Active serving needs an active revision",
                [],
                "None is not of type 'object'",
            ),
            case("operation_publish_verified", pub + "PublicationOperation", OPERATION_VERIFIED, "Verified by reading the rendered revision marker"),
            case("operation_unpublish_verified", pub + "PublicationOperation", OPERATION_UNPUBLISH, "Unpublish verified by reading the empty state"),
            case(
                "operation_verified_without_rendered_hash",
                pub + "PublicationOperation",
                variant(OPERATION_VERIFIED, lambda o: o["verification"].update(rendered_payload_sha256=None)),
                "Revalidation acknowledgement alone is not delivery verification",
                ["verified_means_rendered"],
                "None is not of type 'string'",
            ),
            case(
                "operation_by_moderator",
                pub + "PublicationOperation",
                variant(OPERATION_VERIFIED, lambda o: o.update(actor=MODERATOR)),
                "Only a publisher can publish",
                [],
                "'publisher' was expected",
            ),
            case(
                "operation_delivery_pending_without_activation",
                pub + "PublicationOperation",
                variant(OPERATION_VERIFIED, lambda o: o.update(status="delivery_pending", activated_at=None)),
                "Delivery is pending only after activation",
                [],
                "None is not of type 'string'",
            ),
        ],
        "operations": [
            case("run_insufficient_evidence", ops + "WorkflowRun", RUN_INSUFFICIENT, "A valid result with no content revision and honest coverage", ["insufficient_evidence", "partial_coverage"]),
            case(
                "run_insufficient_with_content",
                ops + "WorkflowRun",
                variant(RUN_INSUFFICIENT, lambda r: r.update(content_revision_id=R1)),
                "Insufficient evidence never produces content",
                ["insufficient_evidence"],
                "is not of type 'null'",
            ),
            case(
                "coverage_access_pending_with_results",
                ops + "RunCoverage",
                variant(COVERAGE[2], lambda c: c.update(fetched=3)),
                "An access_pending connector did not run",
                ["honest_coverage"],
                "0 was expected",
            ),
            case("job_running", ops + "Job", JOB_RUNNING, "Running job holds a lease with a fencing token"),
            case(
                "job_running_without_lease",
                ops + "Job",
                variant(JOB_RUNNING, lambda j: j.update(lease=None)),
                "A running job must hold a lease",
                [],
                "None is not of type 'object'",
            ),
            case("agent_run_coordinator", ops + "AgentRun", agent_run("A00_master_coordinator", None), "The coordinator never calls a model"),
            case("agent_run_extractor", ops + "AgentRun", agent_run("A05_claim_extractor", "claude-sonnet-5"), "Model ID recorded from configuration (D10)"),
            case(
                "agent_run_extractor_without_model",
                ops + "AgentRun",
                agent_run("A05_claim_extractor", None),
                "Model-backed agents record the requested model",
                [],
                "None is not of type 'string'",
            ),
            case("deletion_completed", ops + "DeletionRequest", DELETION_DONE, "Invalidated before erased", ["withdrawal"]),
            case(
                "deletion_erased_before_invalidation",
                ops + "DeletionRequest",
                variant(DELETION_DONE, lambda d: d.update(invalidated_at=None)),
                "Erasure never precedes invalidation",
                ["withdrawal"],
                "None is not of type 'string'",
            ),
            case("correction_received", ops + "PublicCorrection", CORRECTION, "Public correction with no personal data", ["correction"]),
            case(
                "correction_resolved_without_decision",
                ops + "PublicCorrection",
                variant(CORRECTION, lambda c: c.update(status="resolved")),
                "A resolved correction names its decision",
                ["correction"],
                "None is not of type 'string'",
            ),
        ],
        "agents": [
            case("synthesis_abstains", agt + "SynthesisResult", SYNTHESIS_EMPTY, "Valid abstention: no findings are forced", ["insufficient_evidence", "abstention"]),
            case("identity_needs_review", agt + "IdentityResult", IDENTITY, "Ambiguous match left for review, with an alias proposal", ["abstention", "alias_review"]),
            case("claims_unknown_date", agt + "ClaimExtraction", CLAIMS_OUT, "Observation date unknown stays unknown", ["unknown_date"]),
            case(
                "claims_extra_field",
                agt + "ClaimExtraction",
                variant(CLAIMS_OUT, lambda o: o["claims"][0].update(confidence=0.9)),
                "Outputs are closed objects; a model cannot add fields such as a self-rated confidence",
                ["closed_outputs"],
                "Additional properties are not allowed",
            ),
            case(
                "claims_outcome_failed",
                agt + "ClaimExtraction",
                variant(CLAIMS_OUT, lambda o: o.update(outcome="failed")),
                "Only the backend assigns 'failed'",
                ["failed_is_backend_only"],
                "'failed' is not one of",
            ),
            case(
                "verification_opinion",
                agt + "VerificationResult",
                {"outcome": "completed", "verdicts": [{"claim_id": C_OPINION, "status": "not_applicable", "primary_record_ids": [], "contradicting_evidence_ids": [], "reason": "Reported opinion"}]},
                "Opinions are classified, not verified",
            ),
            case(
                "editorial_draft",
                agt + "EditorialDraft",
                {
                    "outcome": "completed",
                    "heading": "What buyers discuss about Fixture Towers",
                    "overview": {"text": "Discussion mostly concerns possession timing.", "caveat": None, "finding_ids": [F_DELAY], "claim_ids": [C_OPINION]},
                    "advantages": [],
                    "considerations": [{"text": "Several buyers report delays.", "caveat": "Not confirmed by the developer.", "finding_ids": [F_DELAY], "claim_ids": [C_OPINION]}],
                    "questions": [],
                    "coverage_note": "Based on 6 public discussions.",
                    "metadata": {"title": "Fixture Towers: what buyers discuss", "description": "Summary of public discussion."},
                },
                "Copy from approved findings only; JSON-LD comes from the backend",
            ),
            case(
                "qa_blocking",
                agt + "QaReport",
                {"outcome": "completed", "issues": [{"block": "considerations", "item_index": 0, "severity": "blocking", "category": "overgeneralisation", "explanation": "'All residents' overstates five posts", "claim_ids": [C_OPINION]}]},
                "QA flags an overgeneralisation; it cannot approve",
            ),
            case(
                "change_review_withdrawn",
                agt + "ChangeReview",
                {"outcome": "completed", "classification": "withdrawn_source", "reasons": ["The forum thread was removed"], "affected_finding_ids": [F_DELAY]},
                "Classifies a withdrawal against the approved manifest",
                ["withdrawal"],
            ),
            case(
                "video_observations",
                agt + "VideoObservations",
                {"outcome": "completed", "observations": [{"segment_id": uid("seg", 1), "modality": "speech", "observation": "The creator says possession was delayed", "speaker": "creator", "start_ms": 12000, "end_ms": 19000, "uncertainty": "Approximate timing", "imagery": None}, {"segment_id": uid("seg", 2), "modality": "on_screen_text", "observation": "Possession December 2027", "speaker": "unknown", "start_ms": 30000, "end_ms": 30001, "uncertainty": None, "imagery": "render_or_graphic"}]},
                "Timestamped observation from an authorised transcript",
            ),
            case(
                "language_context",
                agt + "LanguageContextResult",
                {
                    "outcome": "completed",
                    "items": [
                        {
                            "input_id": E_SPEECH,
                            "language": "hi-Latn",
                            "normalised_text": "possession mein thoda delay hua",
                            "translation": {"language": "en", "text": "possession was delayed a little"},
                            "negation": False,
                            "uncertainty": False,
                            "possible_sarcasm": False,
                            "preserved_terms": ["possession"],
                        }
                    ],
                },
                "Hinglish kept alongside its translation",
            ),
            case(
                "discovery_plan",
                agt + "DiscoveryPlan",
                {
                    "outcome": "completed",
                    "queries": [
                        {"connector_id": "brave_search", "query_text": "\"Fixture Towers\" Sector 0 possession", "window_days": 90, "language": "en", "exclusions": ["Otherville"], "priority": "high", "purpose": "project_name", "category": None},
                        {"connector_id": "brave_search", "query_text": RERA, "window_days": 90, "language": "en", "exclusions": [], "priority": "normal", "purpose": "identifier", "category": None},
                    ],
                },
                "Name and identifier queries",
            ),
            case(
                "review_candidates",
                agt + "ReviewCandidates",
                {
                    "outcome": "completed",
                    "reviews": [
                        {
                            "source_id": S_FORUM,
                            "evidence_ids": [E_FORUM],
                            "perspective": "owner_awaiting_possession",
                            "polarity": "mixed",
                            "aspects": ["unit_layouts_livability", "builder_reputation"],
                            "rendering": "punctuation_normalised",
                            "text": FORUM_REVIEW_TEXT,
                            "translation_note": None,
                        },
                        {
                            "source_id": S_COMMENT,
                            "evidence_ids": [E_COMMENT],
                            "perspective": "site_visit",
                            "polarity": "negative",
                            "aspects": ["builder_reputation"],
                            "rendering": "translated",
                            "text": COMMENT_REVIEW_TEXT,
                            "translation_note": "Translated from Hinglish",
                        },
                    ],
                },
                "A11 proposes one review per source, positive and negative",
                ["source_reviews"],
            ),
            case(
                "review_candidates_paraphrase",
                agt + "ReviewCandidates",
                {
                    "outcome": "completed",
                    "reviews": [
                        {
                            "source_id": S_FORUM,
                            "evidence_ids": [E_FORUM],
                            "perspective": "owner_awaiting_possession",
                            "polarity": "mixed",
                            "aspects": ["builder_reputation"],
                            "rendering": "paraphrase",
                            "text": "Great project overall.",
                            "translation_note": None,
                        }
                    ],
                },
                "The model cannot rewrite a review in its own words",
                ["source_reviews"],
                "'paraphrase' is not one of",
            ),
            case(
                "qa_status_wording",
                agt + "QaReport",
                {"outcome": "completed", "issues": [{"block": "considerations", "item_index": 0, "severity": "blocking", "category": "status_inconsistent", "explanation": "'Residents' used for an under-construction project", "claim_ids": []}]},
                "QA flags wording that does not fit the construction status",
                ["status_consistency"],
            ),
        ],
        "api": [
            case(
                "approval_request",
                api + "ApprovalRequest",
                {"revision": 1, "payload_sha256": REV1["payload_sha256"], "manifest_sha256": REV1["manifest_sha256"], "eligibility_epoch": 3, "expected_state_version": 7},
                "Approval names exactly what the moderator saw",
                ["approval_binding"],
            ),
            case(
                "approval_request_without_manifest",
                api + "ApprovalRequest",
                {"revision": 1, "payload_sha256": REV1["payload_sha256"], "eligibility_epoch": 3, "expected_state_version": 7},
                "The manifest hash is part of the approval",
                ["approval_binding"],
                "'manifest_sha256' is a required property",
            ),
            case("alias_decision_context_required", api + "AliasDecisionRequest", {"action": "approve", "mode": "context_required", "reason": None, "expected_version": 0}, "Approve a generic alias with context", ["alias_review"]),
            case(
                "alias_decision_without_mode",
                api + "AliasDecisionRequest",
                {"action": "approve", "mode": None, "reason": None, "expected_version": 0},
                "Approval must say standalone or context-required",
                ["alias_review"],
                "is not one of",
            ),
            case("correction_request", api + "CorrectionRequest", {"message": "The completion date was revised.", "contact": None, "revision_id": R1, "website": ""}, "Public correction", ["correction"]),
            case(
                "correction_request_honeypot",
                api + "CorrectionRequest",
                {"message": "Buy cheap flats now!!!", "contact": None, "revision_id": None, "website": "http://spam.example.invalid"},
                "The honeypot field must stay empty",
                ["honeypot"],
                "'' was expected",
            ),
            case(
                "link_split",
                api + "LinkDecisionRequest",
                {
                    "action": "split",
                    "expected_version": 1,
                    "reason": "Comparison video covers two projects",
                    "split_segments": [
                        {"segment_key": "t:0-240000", "anchor": time_anchor(0, 240000), "project_id": P},
                        {"segment_key": "t:240000-600000", "anchor": time_anchor(240000, 600000), "project_id": P2},
                    ],
                    "remap_project_id": None,
                    "phase_rera_id": None,
                },
                "Split a comparison video into per-project segments",
                ["multi_project_video"],
            ),
            case(
                "public_insights",
                api + "PublicInsights",
                {"revision_id": R1, "revision": 1, "payload_sha256": REV1["payload_sha256"], "payload": PAYLOAD},
                "Public read of the active revision",
                ["public_read"],
            ),
            case(
                "generate_from_reviews_only",
                api + "ContentRevisionRequest",
                {"mode": "generate", "locale": "en-IN", "findings": [], "reviews": [ref(REX_POST_ID)]},
                "D64: a page from approved reviews alone; the backend refuses a selection with neither findings nor reviews",
                ["source_reviews"],
            ),
            case(
                "generate_with_reviews",
                api + "ContentRevisionRequest",
                {"mode": "generate", "locale": "en-IN", "findings": [ref(F_DELAY)], "reviews": [ref(REX_POST_ID), ref(REX_COMMENT_ID, 2)]},
                "Generate content with approved findings and approved reviews",
                ["source_reviews"],
            ),
            case(
                "review_reject_without_reason",
                api + "ReviewExcerptDecisionRequest",
                {"revision": 1, "action": "reject", "reason": None},
                "Rejecting a review needs a reason",
                ["source_reviews"],
                "None is not of type 'string'",
            ),
            case(
                "review_revision_request",
                api + "ReviewExcerptRevisionRequest",
                {"base": ref(REX_COMMENT_ID), "evidence": [ref(E_COMMENT)], "rendering": "translated", "text": COMMENT_REVIEW_TEXT, "reason": "Fixed one word in the translation"},
                "A moderator fixes a translation as a new revision",
                ["source_reviews"],
            ),
            case(
                "config_patch_empty",
                api + "ProjectConfigPatch",
                {"expected_version": 3},
                "A patch must change something",
                [],
                "does not have enough properties",
            ),
        ],
    }


# --- Vectors -------------------------------------------------------------------------------

EXPECTED_KEY_ORDER = '{"":6,"Z":5,"a":4,"€":1,"😀":2,"ﬀ":3}'


def hashing_vectors() -> dict[str, Any]:
    values = {
        "key_order_utf16": {"€": 1, "😀": 2, "ﬀ": 3, "a": 4, "Z": 5, "": 6},
        "nested_and_literals": {"b": [True, False, None, 0, -1, 9007199254740991], "a": {"y": "", "x": []}},
        "string_escapes": {"s": "quote\" backslash\\ slash/ tab\t newline\n control\u0001 del\u007f sep "},
        "hindi_and_emoji": {"text": nfc("पज़ेशन में देरी 😟"), "n": 3},
        "content_payload_fixture": PAYLOAD,
    }
    cases = []
    for name, value in values.items():
        canonical = ct.canonical_bytes(value).decode("utf-8")
        cases.append({"name": name, "value": value, "canonical": canonical, "sha256": ct.content_hash(value)})
    if cases[0]["canonical"] != EXPECTED_KEY_ORDER:
        raise AssertionError(f"key ordering differs from the hand-derived RFC 8785 order: {cases[0]['canonical']}")
    rejects = [
        {"name": "decimal_number", "value": {"price": 1.5}, "reason": "non-integer number"},
        {"name": "unsafe_integer", "value": {"n": 9007199254740993}, "reason": "integer outside the safe range"},
        {"name": "non_nfc_text", "value": {"t": "é"}, "reason": "text not in NFC"},
        {"name": "non_nfc_key", "value": {"é": 1}, "reason": "key not in NFC"},
    ]
    return {"note": NOTE, "method": "RFC 8785 (JCS) over UTF-8, SHA-256, prefixed 'sha256:' (D23)", "cases": cases, "rejects": rejects}


def anchor_vectors() -> dict[str, Any]:
    samples = [
        ("ascii", "Possession was delayed by six months.", "delayed by six months"),
        ("hindi", "पज़ेशन में छह महीने की देरी हुई", "छह महीने की देरी"),
        ("emoji_before_excerpt", "Great location 😀👍 but parking is tight", "parking is tight"),
        ("emoji_inside_excerpt", "Lift 🚧 abhi tak nahi chali, parking 👎 bhi", "parking 👎 bhi"),
    ]
    cases = []
    for name, text, excerpt in samples:
        text, excerpt = nfc(text), nfc(excerpt)
        start = text.index(excerpt)
        end = start + len(excerpt)
        cases.append(
            {
                "name": name,
                "text": text,
                "excerpt": excerpt,
                "start": start,
                "end": end,
                "utf16_start": ct.utf16_offset(text, start),
                "utf16_end": ct.utf16_offset(text, end),
            }
        )
    return {"note": NOTE, "unit": "Stored offsets are Unicode code points over NFC text; utf16_* are what a browser uses (D24)", "cases": cases}


def rule_vectors() -> dict[str, Any]:
    tampered = variant(REV1, lambda r: r["payload"]["considerations"][0].update(text="Possession was on time."))
    edited_but_approved = variant(REV2, lambda r: r.update(lifecycle="approved"))
    stale_epoch = variant(STATE_ACTIVE, lambda s: s.update(eligibility_epoch=4))
    invalidating = variant(STATE_ACTIVE, lambda s: s.update(pending_invalidation=True))
    approval = [
        {"name": "exact_revision_approved", "decision": APPROVAL, "revision": REV1, "state": STATE_ACTIVE, "authorised": True, "reasons_contain": []},
        {
            "name": "edited_revision_cannot_reuse_approval",
            "decision": APPROVAL,
            "revision": edited_but_approved,
            "state": STATE_ACTIVE,
            "authorised": False,
            "reasons_contain": ["approval names a different revision", "approved payload hash differs from this payload"],
        },
        {
            "name": "tampered_payload_same_revision_number",
            "decision": APPROVAL,
            "revision": tampered,
            "state": STATE_ACTIVE,
            "authorised": False,
            "reasons_contain": ["stored payload hash does not match the payload"],
        },
        {"name": "eligibility_changed_since_approval", "decision": APPROVAL, "revision": REV1, "state": stale_epoch, "authorised": False, "reasons_contain": ["evidence eligibility changed since approval"]},
        {"name": "invalidation_pending", "decision": APPROVAL, "revision": REV1, "state": invalidating, "authorised": False, "reasons_contain": ["an invalidation is pending"]},
    ]
    newer_draft = variant(REV2, lambda r: r.update(created_at=ts(27)))
    mismatched_pointer = variant(STATE_ACTIVE, lambda s: s["active"].update(payload_sha256=REV2["payload_sha256"]))
    public = [
        {"name": "active_not_newest_draft", "state": STATE_ACTIVE, "revisions": [REV1, newer_draft], "serves": R1},
        {"name": "disabled_serves_nothing", "state": STATE_DISABLED, "revisions": [REV1], "serves": None},
        {"name": "unpublished_serves_nothing", "state": STATE_EMPTY, "revisions": [REV1], "serves": None},
        {"name": "pointer_hash_mismatch_serves_nothing", "state": mismatched_pointer, "revisions": [REV1], "serves": None},
    ]
    status_records = CONFIG["construction_status"]
    under_construction = [{"status": "under_construction", "applies_to": {"kind": "project", "rera_id": None}, "basis": "client_export", "as_of": "2026-09-25", "note": None}]
    history = [
        {"status": "under_construction", "applies_to": {"kind": "project", "rera_id": None}, "basis": "client_export", "as_of": "2025-01-01", "note": None},
        {"status": "ready_to_move", "applies_to": {"kind": "project", "rera_id": None}, "basis": "rera_registry", "as_of": "2026-06-01", "note": None},
    ]
    new_launch = [dict(under_construction[0], status="new_launch")]
    status_consistency = [
        {"name": "resident_in_under_construction_project", "records": under_construction, "perspective": "resident_experience", "phase_rera_id": None, "on_date": None, "flags": ["occupancy_before_possession"]},
        {"name": "resident_in_ready_phase", "records": status_records, "perspective": "resident_experience", "phase_rera_id": RERA, "on_date": None, "flags": []},
        {"name": "resident_phase_not_named_in_partly_ready_project", "records": status_records, "perspective": "resident_experience", "phase_rera_id": None, "on_date": None, "flags": ["status_unknown"]},
        {"name": "owner_awaiting_possession_in_new_launch", "records": new_launch, "perspective": "owner_awaiting_possession", "phase_rera_id": None, "on_date": None, "flags": []},
        {"name": "resident_with_no_status_record", "records": [], "perspective": "resident_experience", "phase_rera_id": None, "on_date": None, "flags": ["status_unknown"]},
        {"name": "resident_post_dated_before_handover", "records": history, "perspective": "resident_experience", "phase_rera_id": None, "on_date": "2025-06-15", "flags": ["occupancy_before_possession"]},
        {"name": "resident_post_dated_after_handover", "records": history, "perspective": "resident_experience", "phase_rera_id": None, "on_date": "2026-07-01", "flags": []},
    ]
    status_wording = [
        {"name": "residents_under_construction", "status": "under_construction", "text": "Residents praise the clubhouse.", "blocking": ["residents"], "advice": []},
        {"name": "buyers_under_construction", "status": "under_construction", "text": "Buyers expect the clubhouse by 2027.", "blocking": [], "advice": []},
        {"name": "living_here_new_launch", "status": "new_launch", "text": "People living here like the park.", "blocking": ["living here"], "advice": []},
        {"name": "residents_ready_to_move", "status": "ready_to_move", "text": "Residents praise the clubhouse.", "blocking": [], "advice": []},
        {"name": "residents_partly_ready", "status": "partially_ready", "text": "Residents praise the clubhouse.", "blocking": [], "advice": ["residents"]},
    ]
    clubhouse = "The clubhouse is good. Parking is tight. Lifts work."
    review_rendering = [
        {"name": "dash_changed_to_comma", "original": FORUM_TEXT, "text": FORUM_REVIEW_TEXT, "rendering": "punctuation_normalised", "problems_contain": [], "check": "matches_original"},
        {"name": "word_changed", "original": FORUM_TEXT, "text": FORUM_REVIEW_TEXT.replace("six", "eight"), "rendering": "punctuation_normalised", "problems_contain": ["words differ"], "check": "mismatch"},
        {"name": "words_added", "original": FORUM_TEXT, "text": FORUM_REVIEW_TEXT.replace("in 2024.", "in 2024 and love it."), "rendering": "punctuation_normalised", "problems_contain": ["words differ"], "check": "mismatch"},
        {"name": "verbatim_with_dash", "original": FORUM_TEXT, "text": FORUM_TEXT, "rendering": "verbatim", "problems_contain": ["dash or hyphen"], "check": "mismatch"},
        {"name": "verbatim_exact", "original": OTHER_POST_TEXT, "text": OTHER_POST_TEXT, "rendering": "verbatim", "problems_contain": [], "check": "matches_original"},
        {"name": "sentence_left_out", "original": clubhouse, "text": "The clubhouse is good. Lifts work.", "rendering": "shortened", "problems_contain": [], "check": "matches_original"},
        {"name": "sentences_reordered", "original": clubhouse, "text": "Lifts work. The clubhouse is good.", "rendering": "shortened", "problems_contain": ["sentence"], "check": "mismatch"},
        {"name": "sentence_edited", "original": clubhouse, "text": "The clubhouse is great. Lifts work.", "rendering": "shortened", "problems_contain": ["sentence"], "check": "mismatch"},
        {"name": "translation_goes_to_moderator", "original": COMMENT_TEXT, "text": COMMENT_REVIEW_TEXT, "rendering": "translated", "problems_contain": [], "check": "needs_moderator"},
    ]
    return {
        "note": NOTE,
        "approval": approval,
        "public_read": public,
        "status_consistency": status_consistency,
        "status_wording": status_wording,
        "review_rendering": review_rendering,
    }


def render_all() -> dict[str, str]:
    files = {name: {"note": NOTE, "cases": cases} for name, cases in fixture_cases().items()}
    files["hashing"] = hashing_vectors()
    files["anchors"] = anchor_vectors()
    files["rules"] = rule_vectors()
    return {f"{name}.json": json.dumps(content, indent=2, ensure_ascii=False) + "\n" for name, content in files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a fixture file is missing or stale")
    args = parser.parse_args(argv)
    rendered = render_all()
    if args.check:
        stale = [name for name, text in rendered.items() if not (FIXTURES / name).exists() or (FIXTURES / name).read_text(encoding="utf-8") != text]
        extra = sorted(p.name for p in FIXTURES.glob("*.json") if p.name not in rendered)
        if stale or extra:
            print(f"fixtures out of date: stale={stale} unexpected={extra}; run scripts/build_fixtures.py")
            return 1
        print("fixtures are up to date")
        return 0
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(rendered)} fixture files to {FIXTURES.relative_to(ct.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
