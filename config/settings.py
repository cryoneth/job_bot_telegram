"""Configuration settings loaded from environment variables."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram API credentials (from my.telegram.org)
    telegram_api_id: int = Field(..., description="Telegram API ID")
    telegram_api_hash: str = Field(..., description="Telegram API Hash")

    # Bot token (from @BotFather)
    bot_token: str = Field(..., description="Telegram Bot Token")

    # Owner user ID (for receiving alerts)
    owner_user_id: int = Field(..., description="Your Telegram User ID")

    # Additional authorized users (comma-separated list of user IDs)
    authorized_users: str = Field(
        default="", description="Comma-separated list of additional authorized user IDs"
    )

    @property
    def all_authorized_users(self) -> set[int]:
        """Get all authorized user IDs including owner."""
        users = {self.owner_user_id}
        if self.authorized_users:
            for uid in self.authorized_users.split(","):
                uid = uid.strip()
                if uid.isdigit():
                    users.add(int(uid))
        return users

    # Encryption key (auto-generated if not set)
    cv_encryption_key: Optional[str] = Field(
        default=None, description="Fernet encryption key for CV"
    )

    # Matching threshold (0-100)
    match_threshold: int = Field(
        default=70, ge=0, le=100, description="Minimum match score to trigger alert"
    )

    # Paths
    data_dir: Path = Field(default=Path("data"), description="Data directory")
    session_name: str = Field(
        default="job_monitor_session", description="Telethon session name"
    )

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.data_dir / "jobs.db"

    @property
    def cv_path(self) -> Path:
        """Path to encrypted CV file."""
        return self.data_dir / "cv.enc"

    @property
    def session_path(self) -> Path:
        """Path to Telethon session file."""
        return self.data_dir / f"{self.session_name}.session"

    def ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
