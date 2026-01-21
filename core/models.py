"""Pydantic models for data validation and serialization."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FilterType(str, Enum):
    """Types of job filters."""

    KEYWORD = "keyword"
    EXCLUDED = "excluded"
    LOCATION = "location"
    SENIORITY = "seniority"
    REMOTE = "remote"


class SeniorityLevel(str, Enum):
    """Seniority levels for job positions."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    EXECUTIVE = "executive"


class RemotePreference(str, Enum):
    """Remote work preferences."""

    YES = "yes"
    NO = "no"
    ANY = "any"


class Channel(BaseModel):
    """Monitored Telegram channel."""

    id: Optional[int] = None
    channel_id: str
    channel_name: Optional[str] = None
    added_at: Optional[datetime] = None
    is_active: bool = True


class ProcessedMessage(BaseModel):
    """Record of a processed message for deduplication."""

    id: Optional[int] = None
    channel_id: str
    message_id: int
    content_hash: str
    processed_at: Optional[datetime] = None
    is_job_post: bool = False
    match_score: Optional[int] = None


class Filter(BaseModel):
    """User filter/preference."""

    id: Optional[int] = None
    filter_type: FilterType
    filter_value: str
    is_active: bool = True
    created_at: Optional[datetime] = None


class JobPost(BaseModel):
    """Extracted job post data."""

    role_title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    is_remote: Optional[bool] = None
    seniority: Optional[SeniorityLevel] = None
    salary_info: Optional[str] = None
    requirements: Optional[str] = None
    application_link: Optional[str] = None
    raw_text: str = ""

    @property
    def summary(self) -> str:
        """Get a brief summary of the job post."""
        parts = []
        if self.role_title:
            parts.append(self.role_title)
        if self.company:
            parts.append(f"@ {self.company}")
        return " ".join(parts) if parts else "Job Post"


class MatchResult(BaseModel):
    """Result of CV matching against a job post."""

    score: int = Field(ge=0, le=100)
    match_reasons: list[str] = Field(default_factory=list)
    filter_reasons: list[str] = Field(default_factory=list)
    semantic_score: float = 0.0
    keyword_score: float = 0.0


class MatchedJob(BaseModel):
    """A job post that matched the user's CV."""

    id: Optional[int] = None
    channel_id: str
    message_id: int
    job_post: JobPost
    match_result: MatchResult
    created_at: Optional[datetime] = None

    @property
    def match_score(self) -> int:
        """Get the match score."""
        return self.match_result.score


class TelegramMessage(BaseModel):
    """Incoming Telegram message."""

    channel_id: str
    channel_name: Optional[str] = None
    message_id: int
    text: str
    date: datetime
    link: Optional[str] = None

    @property
    def message_link(self) -> str:
        """Get the Telegram message link."""
        if self.link:
            return self.link
        # Try to construct link from channel ID
        channel = self.channel_id.lstrip("-100")
        return f"https://t.me/c/{channel}/{self.message_id}"


class BotStatus(BaseModel):
    """Current bot status."""

    is_running: bool = False
    is_paused: bool = False
    channels_count: int = 0
    processed_count: int = 0
    matched_count: int = 0
    filters_count: int = 0
    has_cv: bool = False
    match_threshold: int = 70
    last_match: Optional[datetime] = None


class UserFilters(BaseModel):
    """Collection of user filters."""

    keywords: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    seniorities: list[SeniorityLevel] = Field(default_factory=list)
    remote: RemotePreference = RemotePreference.ANY
    threshold: int = 70

    @classmethod
    def from_db_filters(cls, filters: list[dict]) -> "UserFilters":
        """Create UserFilters from database filter records."""
        result = cls()
        for f in filters:
            filter_type = f.get("filter_type")
            value = f.get("filter_value", "")
            if filter_type == FilterType.KEYWORD.value:
                result.keywords.append(value)
            elif filter_type == FilterType.EXCLUDED.value:
                result.excluded.append(value)
            elif filter_type == FilterType.LOCATION.value:
                result.locations.append(value)
            elif filter_type == FilterType.SENIORITY.value:
                try:
                    result.seniorities.append(SeniorityLevel(value))
                except ValueError:
                    pass
            elif filter_type == FilterType.REMOTE.value:
                try:
                    result.remote = RemotePreference(value)
                except ValueError:
                    pass
        return result
