"""Settings loaded from environment variables (and .env locally).

Every deployment difference (Vercel now, self-hosted later) is a setting here,
never a code change. See docs/spec/10-free-tier-and-portability.md.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # Database and storage (Supabase now; plain Postgres / local disk later)
    database_url: str = Field(
        default="", validation_alias=AliasChoices("DATABASE_SESSION_POOL_URL", "DATABASE_URL")
    )
    supabase_url: str = Field(
        default="", validation_alias=AliasChoices("DATABASE_PROJECT_URL", "SUPABASE_URL")
    )
    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    blob_store: Literal["supabase", "local"] = "local"
    local_blob_dir: Path = ROOT_DIR / ".data" / "blobs"

    # LLM providers. llm_mode "off" and "replay" never make network calls;
    # "live" is only used after an explicitly approved smoke test or in production.
    llm_mode: Literal["off", "replay", "live"] = "off"
    llm_primary: Literal["deepseek", "groq"] = "deepseek"
    llm_record: bool = False  # in live mode, also write replay fixtures
    llm_fixture_dir: Path = ROOT_DIR / "tests" / "fixtures" / "llm"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_fast_model: str = "deepseek-flash"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_s: float = 60.0

    # Search and performance providers
    serper_api_key: str = ""
    serpapi_key: str = Field(default="", validation_alias=AliasChoices("SERP_API_KEY", "SERPAPI_KEY"))
    serper_calls_per_run: int = 40
    serpapi_calls_per_run: int = 8  # free plan: 250/month
    # Wikimedia's API refuses requests without contact details in the User-Agent (an email or URL).
    wikimedia_contact: str = Field(default="", validation_alias=AliasChoices("WIKIMEDIA_CONTACT"))
    pagespeed_urls_per_run: int = 5  # PageSpeed Insights is free (25,000 calls/day); each call takes 10–40 s
    pagespeed_api_key: str = Field(
        default="", validation_alias=AliasChoices("PAGE_SPEED_API_KEY", "PAGESPEED_API_KEY")
    )

    # Execution
    deploy_target: Literal["vercel", "local"] = "local"
    runner: Literal["inline", "http"] = "inline"
    app_base_url: str = Field(default_factory=lambda: (
        f"https://{os.environ['VERCEL_URL']}" if os.environ.get("VERCEL_URL") else "http://127.0.0.1:8000"
    ))
    internal_secret: str = ""  # HMAC secret for /internal endpoints (required when runner=http)
    engine_api_key: str = ""  # bearer key for the REST API (required outside local)
    vercel_automation_bypass_secret: str = ""  # server-to-server calls to a protected preview
    # Workspace previews: pages the dashboard may frame (space-separated origins), and the key that
    # signs short-lived preview links (falls back to internal_secret, then a per-process key).
    dashboard_origins: str = Field(default_factory=lambda: (
        f"https://{os.environ['VERCEL_URL']}" if os.environ.get("VERCEL_URL")
        else "http://localhost:3000 http://127.0.0.1:3000"
    ))
    preview_secret: str = ""
    renderer_url: str = ""  # empty = rendering skipped
    task_lease_s: int = 360
    task_max_attempts: int = 3
    run_max_concurrency: int = 6

    # Crawling
    crawl_cap_default: int = 25
    crawl_user_agent: str = "Mozilla/5.0 (compatible; SiteDiagnosisBot/0.1)"
    crawl_timeout_s: float = 20.0
    crawl_max_bytes: int = 5_000_000
    crawl_concurrency: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
