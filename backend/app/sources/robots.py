"""robots.txt decisions (RFC 9309; docs/06 rule 2). Asked before every fetch; each verdict is recorded. Whether a
verdict blocks the fetch is the source policy's choice (`robots_txt`: obey or record_only, D46).

- 2xx: parsed and applied to our user-agent token;
- 404 or 410 (there is no robots.txt): everything is allowed;
- any other 4xx (401, 403, 429...): the verdict is `robots_refused` (disallow everything). Found live on 30 Sep
  2026: sites behind bot protection answered robots.txt with 403 and a challenge page;
- 5xx, timeout or a refused connection: nothing is fetched from that host for now (conservative);
- results are cached per host for `ttl` seconds.
"""

from __future__ import annotations

import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.sources.http import FetchError, SafeClient


@dataclass
class RobotsDecision:
    allowed: bool
    basis: str  # parsed | no_robots_file | robots_refused | robots_unreachable
    robots_url: str


class RobotsCache:
    def __init__(
        self, client: SafeClient, agent_token: str, ttl: float = 86400.0, clock: Callable[[], float] = time.time
    ):
        self.client, self.agent_token, self.ttl, self.clock = client, agent_token, ttl, clock
        self._cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None, str]] = {}

    def _load(self, origin: str) -> tuple[urllib.robotparser.RobotFileParser | None, str]:
        robots_url = f"{origin}/robots.txt"
        try:
            response = self.client.get(robots_url, accept=("text/plain", "text/html", ""))
        except FetchError:
            return None, "robots_unreachable"
        if response.status in (404, 410):
            parser = urllib.robotparser.RobotFileParser()
            parser.parse([])
            return parser, "no_robots_file"
        if 400 <= response.status < 500:
            return None, "robots_refused"
        if response.status >= 500:
            return None, "robots_unreachable"
        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(response.text().splitlines())
        except Exception:
            return None, "robots_unreadable"
        return parser, "parsed"

    def decide(self, url: str) -> RobotsDecision:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._cache.get(origin)
        if cached is None or self.clock() - cached[0] > self.ttl:
            parser, basis = self._load(origin)
            cached = (self.clock(), parser, basis)
            self._cache[origin] = cached
        _, parser, basis = cached
        allowed = parser is not None and parser.can_fetch(self.agent_token, url)
        return RobotsDecision(allowed=allowed, basis=basis, robots_url=f"{origin}/robots.txt")
