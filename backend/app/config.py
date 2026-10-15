"""Validated settings (docs/01 configuration contract).

Every value comes from the environment or the repository's `.env`. Live mode
fails fast when a required setting is missing; fixture mode is explicit and can
never publish (D09, docs/01). Provider keys are optional: a missing key means
the connector stays `access_pending` (D06).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Mode(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,  # a failed start must not echo credentials into logs
    )

    app_mode: Mode = Mode.FIXTURE
    log_level: str = "INFO"

    mongodb_uri: str = "mongodb://localhost:27017/?replicaSet=rs0&directConnection=true"
    mongodb_db: str = "sy_poc"

    session_secret: SecretStr | None = None
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3000"
    login_attempts_per_window: int = Field(default=10, ge=1)
    corrections_per_hour: int = Field(default=5, ge=1)  # public correction reports per client address
    login_window_minutes: int = Field(default=15, ge=1)

    anthropic_api_key: SecretStr | None = None
    # Only for an organisation-level key: the workspace its requests run in (sent as anthropic-workspace-id).
    anthropic_workspace_id: str | None = Field(default=None, pattern=r"^wrkspc_[A-Za-z0-9]+$")
    model_light: str = "claude-haiku-5-5"  # Step 08 (D53): bulk extraction and curation, the cheapest current model
    model_routine: str = "claude-sonnet-5"
    model_reasoning: str = "claude-sonnet-5"
    model_difficult: str = "claude-opus-5-5"
    # Below 21,333 the SDK allows a non-streaming call (3,600 s per 128,000 tokens over 600 s); agents set their own.
    model_max_output_tokens: int = Field(default=16000, ge=256, le=21000)
    model_timeout_seconds: float = Field(default=300.0, ge=30)
    model_max_attempts: int = Field(default=3, ge=1, le=6)
    # Prompt caching (D65, product owner 13 Oct 2026: "Use Claude's Prompt caching as well"). One explicit cache
    # breakpoint on the agent's instructions (the system prompt), the prefix every task of that agent shares; never on
    # the task's own evidence, which no other call repeats (automatic top-level caching cached that too: on 13 Oct all
    # 25 evaluation calls wrote the cache and none read it). The breakpoint is set only when the instructions reach the
    # model's minimum cacheable length; shorter prefixes are not cached by the API and are sent plain. Realtime calls
    # use the 5-minute cache (an agent's tasks run back to back); batches use the 1-hour cache, as Anthropic advises
    # for batches, whose requests run concurrently and later.
    model_prompt_cache: bool = True
    model_cache_ttl: str = Field(default="5m", pattern=r"^(5m|1h)$")
    model_batch_cache_ttl: str = Field(default="1h", pattern=r"^(5m|1h)$")
    # Minimum cacheable prefix per model, from Anthropic's prompt-caching documentation (checked 13 Oct 2026).
    model_cache_min_tokens: dict[str, int] = {
        "claude-haiku-5-5": 512,
        "claude-sonnet-5": 1024,
        "claude-sonnet-5-5": 512,
        "claude-opus-5-5": 512,
    }

    # Spend (Step 08, D53): a hard cap on live model calls, counted from MODEL_BUDGET_SINCE. Prices are USD per
    # million tokens from Anthropic's published table (9 Oct 2026); the Batch API halves input and output.
    model_budget_usd: float = Field(default=3.0, ge=0)  # D53 $2, raised to $3 by the product owner (D61)
    model_budget_since: datetime = datetime(2026, 10, 9, tzinfo=UTC)
    model_prices: dict[str, dict[str, float]] = {
        "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
        "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_write": 2.50, "cache_read": 0.20},
        "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_write": 2.50, "cache_read": 0.10},
        "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20},
    }

    job_lease_seconds: int = Field(default=60, ge=5)
    job_max_attempts: int = Field(default=5, ge=1)
    job_poll_seconds: float = Field(default=2.0, gt=0)
    run_budget_usd: float = Field(default=5.0, ge=0)
    # Step 08: how long an analysis waits for transcripts and origin grouping before going ahead with what is there.
    analysis_input_wait_minutes: int = Field(default=240, ge=0)

    # Collection (Step 05, docs/06). The crawler identifies itself honestly; limits are per host and per provider.
    crawler_user_agent: str = "ProjectIntelligenceBot/0.1 (project research POC)"  # no claim it cannot keep (D46)
    crawler_min_seconds_per_host: float = Field(default=3.0, ge=0)
    crawler_max_bytes: int = Field(default=3_000_000, ge=10_000)
    crawler_max_redirects: int = Field(default=5, ge=0, le=10)
    crawler_timeout_seconds: float = Field(default=20.0, gt=0)
    brave_monthly_queries: int = Field(default=2000, ge=0)
    brave_pages_per_query: int = Field(default=2, ge=1, le=10)
    youtube_daily_searches: int = Field(default=100, ge=0)
    youtube_daily_units: int = Field(default=10_000, ge=0)
    youtube_searches_per_project: int = Field(default=4, ge=0)
    youtube_comment_pages_per_video: int = Field(default=3, ge=0)
    # Step 08 (D54): Instagram public posts through Scrapfly. Credits are reserved before each request.
    scrapfly_monthly_credits: int = Field(default=1000, ge=0)
    scrapfly_credits_per_post: int = Field(default=30, ge=1)
    instagram_posts_per_project: int = Field(default=5, ge=0)
    instagram_queries_per_project: int = Field(default=2, ge=0)
    # Step 08 (D60): competitor-portal pages that refuse the web reader, read through Scrapfly, per collection job.
    unblocked_pages_per_run: int = Field(default=5, ge=0)
    # Paid providers (Scrapfly, Firecrawl): longer than their own timeouts; one attempt (a resend may be billed).
    paid_provider_timeout_seconds: float = Field(default=180.0, ge=10)
    # Step 08 (D62): pages built by JavaScript rendered through Firecrawl, per collection job, from a monthly ledger.
    rendered_pages_per_run: int = Field(default=10, ge=0)
    firecrawl_monthly_credits: int = Field(default=500, ge=0)
    firecrawl_credits_per_page: int = Field(default=1, ge=1)
    web_pages_per_run: int = Field(default=80, ge=0)
    # A collect job (one source group) stops where it is after this long, keeping what it stored (audit, 14 Oct 2026).
    collect_job_max_minutes: int = Field(default=30, ge=1)  # 40 until D61 opened the generic web route
    # Reddit through PullPush (D67, D68): names searched per project, posts and comment hits per name, threads read.
    reddit_names_per_project: int = Field(default=4, ge=0)
    reddit_posts_per_name: int = Field(default=25, ge=0, le=100)
    reddit_comment_hits_per_name: int = Field(default=50, ge=0, le=100)
    reddit_threads_per_run: int = Field(default=30, ge=0)
    reddit_comments_per_thread: int = Field(default=100, ge=1, le=100)
    # Threads PullPush has no comments for, read from Reddit's JSON through Scrapfly: spends credits, off by default.
    reddit_threads_via_scrapfly_per_run: int = Field(default=0, ge=0)
    # The analysis (D68): "reviews" curates first-person reviews only (A11); "full" also extracts claims and findings.
    analysis_mode: str = Field(default="reviews", pattern="^(reviews|full)$")
    # The published page (D69): at most this many reviews, each 30 to 80 words (A11 keeps only reviews in the range).
    page_reviews_max: int = Field(default=20, ge=1, le=100)
    review_words_min: int = Field(default=30, ge=1)
    review_words_max: int = Field(default=80, ge=1)
    identity_agent_tasks_per_run: int = Field(default=10, ge=0)
    recheck_per_job: int = Field(default=200, ge=0)

    # Media (Step 06, D47). Only project-linked public videos; audio is deleted after transcription.
    # media: only process_media jobs; journeys: the browser journeys' worker (no collection, analysis or media)
    worker_role: str = Field(default="all", pattern="^(all|general|media|journeys)$")
    media_caption_languages: str = "hi,en,en-IN"
    media_max_duration_seconds: int = Field(default=600, ge=10)
    media_max_audio_bytes: int = Field(default=60_000_000, ge=100_000)
    media_window_target_ms: int = Field(default=30_000, ge=5_000)
    media_window_max_ms: int = Field(default=45_000, ge=10_000)
    media_videos_per_start: int = Field(default=50, ge=0)
    media_work_dir: Path = Path("/tmp/media")  # noqa: S108  (a tmpfs in the media worker; emptied after each job)
    # Frames (Step 06.5, D49): the video at 480p or lower, sampled frames read by A03; never stored.
    media_frames_enabled: bool = True
    media_frames_per_video: int = Field(default=12, ge=1, le=20)
    media_frame_width: int = Field(default=768, ge=256, le=1568)
    media_max_video_bytes: int = Field(default=150_000_000, ge=1_000_000)
    whisper_model: str = "large-v3-turbo"  # evals/media/v1: far better Hindi than small; about 1-2x real time on an M1
    whisper_compute_type: str = "int8"
    whisper_models_dir: Path = Path("/srv/models")

    # Embeddings (Step 07, D51): bge-m3 int8 ONNX in the embedder service; pinned commit and file hashes.
    embedding_enabled: bool = True
    embedding_url: str = "http://embedder:8100"
    embedding_model: str = "Xenova/bge-m3"  # the ONNX export of BAAI/bge-m3 (MIT)
    embedding_revision: str = "4de13258303883538bd53b696b452bf8099f0858"
    embedding_file: str = "onnx/model_int8.onnx"
    embedding_sha256: str = "a206e10e995aa2a833924bcd725ba5dd6c3425cd34bac3cf2b5677cd2a1c51d6"
    embedding_tokenizer_sha256: str = "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"
    embedding_dim: int = 1024
    embedding_max_tokens: int = Field(default=512, ge=16, le=8192)
    embedding_threads: int = Field(default=2, ge=1, le=16)
    # One text per request: batches of 8 long texts pushed the 1.5 GB embedder into swap and made it 13 times slower
    embedding_batch: int = Field(default=1, ge=1, le=64)
    embedding_query_timeout_seconds: float = Field(default=15.0, gt=0)  # then search falls back to keywords
    embedding_job_timeout_seconds: float = Field(default=300.0, gt=0)
    embedding_models_dir: Path = Path("/srv/embeddings")

    public_base_url: str = "http://localhost:3000"
    # Where the worker reaches the web app to refresh and read the public page (delivery verification, docs/05);
    # inside Compose the web service, not the browser's address.
    web_internal_url: str = "http://localhost:3000"
    revalidation_secret: SecretStr | None = None

    brave_search_api_key: SecretStr | None = None
    scrapfly_api_key: SecretStr | None = None  # Instagram public posts (I20)
    firecrawl_api_key: SecretStr | None = None
    youtube_api_key: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    x_bearer_token: SecretStr | None = None
    meta_access_token: SecretStr | None = None
    listening_provider_api_key: SecretStr | None = None

    contracts_dir: Path = REPO_ROOT / "contracts"
    seed_dir: Path = REPO_ROOT / "seed"

    @model_validator(mode="after")
    def _required_in_live_mode(self) -> Settings:
        if self.app_mode is Mode.LIVE:
            missing = [
                name
                for name in ("session_secret", "revalidation_secret")
                if getattr(self, name) is None or len(getattr(self, name).get_secret_value()) < 32
            ]
            if missing:
                raise ValueError(
                    f"live mode needs {', '.join(n.upper() for n in missing)} set to at least 32 characters"
                )
        elif self.session_secret is None:
            # Fixture mode only: an ephemeral secret, so sessions end when the process restarts.
            self.session_secret = SecretStr(secrets.token_urlsafe(48))
        return self

    def model_for_role(self, role: str) -> str:
        return {
            "light": self.model_light,
            "routine": self.model_routine,
            "reasoning": self.model_reasoning,
            "difficult": self.model_difficult,
        }[role]

    def credential_present(self, env_name: str) -> bool:
        value = getattr(self, env_name.lower(), None)
        return isinstance(value, SecretStr) and bool(value.get_secret_value())

    def secret_values(self) -> list[str]:
        """Every configured secret, for log redaction."""
        return [
            value.get_secret_value()
            for value in self.__dict__.values()
            if isinstance(value, SecretStr) and len(value.get_secret_value()) >= 8
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
