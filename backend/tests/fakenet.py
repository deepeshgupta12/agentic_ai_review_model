"""A fake internet for connector and collection tests: a mock transport routed by host and path, and a fake
DNS table of public addresses. Pages and API answers are fictional."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from app.sources.http import FetchError, HostPacer, SafeClient

Handler = Callable[[httpx.Request], httpx.Response]


class FakeNet:
    def __init__(self) -> None:
        self.routes: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def route(self, host: str, handler: Handler) -> None:
        self.routes[host] = handler

    def html(self, host: str, pages: dict[str, tuple[int, str]], robots: str = "User-agent: *\nAllow: /\n") -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, headers={"content-type": "text/plain"}, text=robots)
            status, body = pages.get(request.url.path, (404, "not found"))
            return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8"}, text=body)

        self.route(host, handler)

    def json(self, host: str, answer: Callable[[httpx.Request], tuple[int, Any]]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            status, body = answer(request)
            return httpx.Response(
                status, headers={"content-type": "application/json"}, content=json.dumps(body).encode()
            )

        self.route(host, handler)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.host)
        if handler is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, text="no such host in the fake net")
        return handler(request)

    def resolver(self, host: str) -> list[str]:
        if host in self.routes or host.startswith("www."):
            return ["93.184.216.34"]
        raise FetchError("dns_failed", f"{host} did not resolve", retryable=True)

    def client(self, user_agent: str = "ProjectIntelligenceBot/0.1 (test)") -> SafeClient:
        return SafeClient(
            user_agent=user_agent,
            max_bytes=500_000,
            max_redirects=3,
            timeout=5,
            pacer=HostPacer(0),
            resolver=self.resolver,
            transport=httpx.MockTransport(self.handle),
            sleep=lambda _s: None,
        )

    def hosts_requested(self) -> list[str]:
        return [r.url.host for r in self.requests]


def article(title: str, body: str, date: str = "2026-08-14") -> str:
    return (
        f'<html lang="en"><head><title>{title}</title><meta name="author" content="A Writer">'
        f'<meta property="article:published_time" content="{date}T09:30:00+05:30"></head><body><article>'
        f"<h1>{title}</h1><p>{body}</p><p>{body}</p></article></body></html>"
    )
