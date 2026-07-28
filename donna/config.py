"""Central configuration, loaded from environment variables / .env.

Everything secret lives here and nowhere else. Import `settings` anywhere
you need a value; never read os.environ directly elsewhere.
"""
from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Brain
    # Secret/identity fields default to empty so the app can boot in DEMO mode
    # without credentials; call require_live() before doing anything real.
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    model_draft: str = Field("claude-opus-4-8", alias="DONNA_MODEL_DRAFT")
    model_triage: str = Field("claude-sonnet-5", alias="DONNA_MODEL_TRIAGE")

    # Owner
    owner_telegram_id: int = Field(0, alias="OWNER_TELEGRAM_ID")
    owner_name: str = Field("there", alias="OWNER_NAME")
    owner_email: str = Field("", alias="OWNER_EMAIL")
    owner_timezone: str = Field("UTC", alias="OWNER_TIMEZONE")

    # Telegram
    telegram_api_id: int = Field(0, alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field("", alias="TELEGRAM_API_HASH")
    telegram_session: str = Field("", alias="TELEGRAM_SESSION")

    # Google
    google_client_secret_file: str = Field(
        "client_secret.json", alias="GOOGLE_CLIENT_SECRET_FILE"
    )
    google_token_json: str = Field("", alias="GOOGLE_TOKEN_JSON")

    # Monday.com (optional project source)
    monday_api_token: str = Field("", alias="MONDAY_API_TOKEN")
    monday_board_ids: str = Field("", alias="MONDAY_BOARD_IDS")  # comma-separated board ids

    @property
    def monday_boards(self) -> list[str]:
        return [b.strip() for b in self.monday_board_ids.split(",") if b.strip()]

    # Behavior
    comms_autonomy: str = Field("draft", alias="COMMS_AUTONOMY")  # draft | auto_low
    calendar_autonomy: str = Field("auto", alias="CALENDAR_AUTONOMY")  # auto | ask
    inbox_poll_minutes: int = Field(10, alias="INBOX_POLL_MINUTES")
    brief_time: str = Field("07:30", alias="BRIEF_TIME")
    nudge_after_days: int = Field(3, alias="NUDGE_AFTER_DAYS")

    # Storage
    database_url: str = Field("sqlite:///donna.db", alias="DATABASE_URL")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.owner_timezone)

    @property
    def brief_hour_minute(self) -> tuple[int, int]:
        h, m = self.brief_time.split(":")
        return int(h), int(m)

    def require_live(self) -> None:
        """Raise if credentials needed for real operation are missing."""
        missing = [n for n, v in {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OWNER_EMAIL": self.owner_email,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Missing required config: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
