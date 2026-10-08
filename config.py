"""
Runtime settings, read once from the environment (and from .env when running locally).

Every limit that decides when a group stops using the bot lives here, so it can be changed with an
environment variable instead of a code change.
"""

import os
import secrets
import logging
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

log = logging.getLogger("config")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    on_cloud_run: bool
    public_base_url: str

    # LINE
    line_channel_secret: str
    line_channel_access_token: str
    line_admin_user_id: str
    line_bot_basic_id: str

    # Models and data sources
    gmi_api_key: str
    gmi_base_url: str
    gmi_model: str
    ekispert_api_key: str
    ekispert_mcp_url: str
    hotpepper_api_key: str
    places_api_key: str

    # Our own secrets
    app_secret: str          # hashes LINE IDs and signs links
    admin_api_token: str     # unlocks the live (paid) web simulator endpoints

    # Infrastructure
    store_backend: str       # "memory" | "firestore"
    gcp_project: str
    region: str
    form_agent_mode: str     # "off" | "local" | "job"
    form_agent_job: str

    # Limits: when a group (and the whole service) stops
    plans_per_group: int
    searches_per_group: int
    group_active_days: int
    activation_window_hours: int
    max_participants: int
    groups_per_user: int
    daily_search_limit: int
    daily_llm_limit: int
    daily_places_limit: int
    daily_simulator_limit: int
    daily_agent_limit: int
    invite_ttl_days: int
    held_messages_max: int
    group_retention_days: int


def _load() -> Settings:
    load_dotenv()
    on_cloud_run = bool(os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"))

    app_secret = os.getenv("APP_SECRET", "")
    if not app_secret:
        if on_cloud_run:
            raise RuntimeError("APP_SECRET must be set on Cloud Run")
        # Local development only: hashed IDs change on every restart, which is fine with the memory store.
        app_secret = secrets.token_urlsafe(32)
        log.warning("APP_SECRET not set; using a temporary one for this process")

    return Settings(
        on_cloud_run=on_cloud_run,
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        line_channel_secret=os.getenv("LINE_CHANNEL_SECRET", ""),
        line_channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        line_admin_user_id=os.getenv("LINE_ADMIN_USER_ID", ""),
        line_bot_basic_id=os.getenv("LINE_BOT_BASIC_ID", ""),
        gmi_api_key=os.getenv("GMI_API_KEY", ""),
        gmi_base_url=(os.getenv("GMI_BASE_URL") or "https://api.gmi-serving.com/v1"),
        gmi_model=(os.getenv("GMI_MODEL") or "Qwen/Qwen3.8-Flash"),
        ekispert_api_key=os.getenv("EKISPERT_API_ACCESS_KEY", ""),
        ekispert_mcp_url=(os.getenv("EKISPERT_MCP_URL") or "https://api-mcp.ekispert.jp/mcp"),
        hotpepper_api_key=os.getenv("HOTPEPPER_API_KEY", ""),
        places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", ""),
        app_secret=app_secret,
        admin_api_token=os.getenv("ADMIN_API_TOKEN", ""),
        store_backend=os.getenv("STORE_BACKEND", "firestore" if on_cloud_run else "memory"),
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        region=(os.getenv("REGION") or "asia-northeast1"),
        form_agent_mode=(os.getenv("FORM_AGENT_MODE") or "off"),
        form_agent_job=(os.getenv("FORM_AGENT_JOB") or "asobi-form-agent"),
        plans_per_group=_int("PLANS_PER_GROUP", 1),
        searches_per_group=_int("SEARCHES_PER_GROUP", 3),
        group_active_days=_int("GROUP_ACTIVE_DAYS", 7),
        activation_window_hours=_int("ACTIVATION_WINDOW_HOURS", 24),
        max_participants=_int("MAX_PARTICIPANTS", 10),
        groups_per_user=_int("GROUPS_PER_USER", 2),
        daily_search_limit=_int("DAILY_SEARCH_LIMIT", 100),
        daily_llm_limit=_int("DAILY_LLM_LIMIT", 300),
        daily_places_limit=_int("DAILY_PLACES_LIMIT", 30),
        daily_simulator_limit=_int("DAILY_SIMULATOR_LIMIT", 60),
        daily_agent_limit=_int("DAILY_AGENT_LIMIT", 20),
        invite_ttl_days=_int("INVITE_TTL_DAYS", 14),
        held_messages_max=_int("HELD_MESSAGES_MAX", 50),
        group_retention_days=_int("GROUP_RETENTION_DAYS", 90),
    )


@lru_cache
def get_settings() -> Settings:
    return _load()
