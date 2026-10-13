"""Build connectors from settings. A connector without its credential is not built: it stays access_pending
and a run records it as not run (docs/06)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Connector
from app.sources.http import HostPacer, SafeClient
from app.sources.robots import RobotsCache

_PACER: HostPacer | None = None


def safe_client(settings: Settings) -> SafeClient:
    global _PACER
    if _PACER is None or _PACER.interval != settings.crawler_min_seconds_per_host:
        _PACER = HostPacer(settings.crawler_min_seconds_per_host)
    return SafeClient(
        user_agent=settings.crawler_user_agent,
        max_bytes=settings.crawler_max_bytes,
        max_redirects=settings.crawler_max_redirects,
        timeout=settings.crawler_timeout_seconds,
        pacer=_PACER,
    )


def agent_token(settings: Settings) -> str:
    return settings.crawler_user_agent.split("/", 1)[0].strip()


def build(connector_id: str, db: Database[dict[str, Any]], settings: Settings) -> Connector | None:
    """The live adapter, or None when its credential is missing (access_pending)."""
    if connector_id == "brave_search":
        from app.connectors.brave import BraveSearch

        key = settings.brave_search_api_key
        return BraveSearch(key.get_secret_value(), safe_client(settings), db, settings) if key else None
    if connector_id == "youtube_data_api":
        from app.connectors.youtube import YouTubeDataApi

        key = settings.youtube_api_key
        return YouTubeDataApi(key.get_secret_value(), safe_client(settings), db, settings) if key else None
    if connector_id == "harera_registry":
        from app.connectors.harera import MAX_LISTING_BYTES, HareraRegistry

        client = safe_client(settings)
        client.max_bytes = max(client.max_bytes, MAX_LISTING_BYTES)  # a fresh client per build; the list is large
        return HareraRegistry(client, RobotsCache(client, agent_token(settings)), db)
    if connector_id == "instagram_public":  # D54: discovery needs Brave, reading needs Scrapfly
        from app.connectors.instagram import InstagramPublic

        key = settings.scrapfly_api_key
        brave = build("brave_search", db, settings)
        if key is None or brave is None:
            return None
        client = safe_client(settings)
        return InstagramPublic(
            key.get_secret_value(), client, RobotsCache(client, agent_token(settings)), db, settings, brave
        )
    if connector_id == "web_fetch":
        from app.connectors.web import WebFetch

        client = safe_client(settings)
        return WebFetch(client, RobotsCache(client, agent_token(settings)), db)
    return None
