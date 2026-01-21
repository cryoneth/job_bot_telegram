"""Message deduplication service."""

import hashlib
import logging
import re
from typing import Optional

from core.database import Database
from core.models import TelegramMessage

logger = logging.getLogger(__name__)


class Deduplicator:
    """Handles message deduplication to avoid processing the same job post twice."""

    def __init__(self, database: Database, dedup_window_days: int = 7):
        """
        Initialize the deduplicator.

        Args:
            database: Database instance for persistence
            dedup_window_days: Number of days to check for duplicates
        """
        self._db = database
        self._dedup_window = dedup_window_days

    async def is_duplicate(self, message: TelegramMessage) -> bool:
        """
        Check if a message is a duplicate.

        A message is considered duplicate if:
        1. Same channel_id + message_id was already processed
        2. Same content hash exists within the dedup window

        Args:
            message: The Telegram message to check

        Returns:
            True if duplicate, False if new
        """
        # Check exact message ID duplicate
        if await self._db.is_message_processed(message.channel_id, message.message_id):
            logger.debug(f"Duplicate message ID: {message.channel_id}/{message.message_id}")
            return True

        # Check content hash duplicate
        content_hash = self._compute_content_hash(message.text)
        if await self._db.is_content_duplicate(content_hash, self._dedup_window):
            logger.debug(f"Duplicate content hash: {content_hash[:16]}...")
            return True

        return False

    async def mark_processed(
        self,
        message: TelegramMessage,
        is_job_post: bool = False,
        match_score: Optional[int] = None,
    ) -> None:
        """
        Mark a message as processed.

        Args:
            message: The processed message
            is_job_post: Whether it was identified as a job post
            match_score: The CV match score (if applicable)
        """
        content_hash = self._compute_content_hash(message.text)
        await self._db.add_processed_message(
            channel_id=message.channel_id,
            message_id=message.message_id,
            content_hash=content_hash,
            is_job_post=is_job_post,
            match_score=match_score,
        )

    def _compute_content_hash(self, text: str) -> str:
        """
        Compute a hash of the message content for near-duplicate detection.

        The hash is normalized to handle minor variations:
        - Lowercased
        - Whitespace normalized
        - URLs normalized (not removed, to handle URL-only messages)
        - Numbers removed (salary figures may vary)

        Args:
            text: Message text

        Returns:
            SHA256 hash of normalized content
        """
        normalized = self._normalize_text(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for comparison.

        Args:
            text: Original text

        Returns:
            Normalized text
        """
        # Lowercase
        text = text.lower()

        # Extract URLs first
        urls = re.findall(r"https?://\S+", text)

        # Remove URLs from text
        text_without_urls = re.sub(r"https?://\S+", "", text)

        # Remove email addresses
        text_without_urls = re.sub(r"\S+@\S+\.\S+", "", text_without_urls)

        # Remove numbers (but keep alphanumeric identifiers)
        text_without_urls = re.sub(r"\b\d+\b", "", text_without_urls)

        # Normalize whitespace
        text_without_urls = " ".join(text_without_urls.split()).strip()

        # If message was URL-only or mostly URL, include normalized URLs in hash
        if len(text_without_urls) < 20 and urls:
            # Normalize URLs (remove tracking params, keep path)
            normalized_urls = []
            for url in urls:
                # Keep domain and path, remove query params for dedup
                url = re.sub(r"\?.*$", "", url)  # Remove query string
                url = url.rstrip("/")  # Remove trailing slash
                normalized_urls.append(url)
            return " ".join(normalized_urls)

        return text_without_urls

    async def cleanup_old(self, days: int = 30) -> int:
        """
        Clean up old processed message records.

        Args:
            days: Delete records older than this many days

        Returns:
            Number of records deleted
        """
        count = await self._db.cleanup_old_messages(days)
        if count > 0:
            logger.info(f"Cleaned up {count} old message records")
        return count


class LinkExtractor:
    """Extract and compare links from messages for deduplication."""

    # Common job platform domains
    JOB_DOMAINS = {
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "monster.com",
        "lever.co",
        "greenhouse.io",
        "workable.com",
        "breezy.hr",
        "recruitee.com",
        "smartrecruiters.com",
        "jobs.lever.co",
        "boards.greenhouse.io",
        "apply.workable.com",
    }

    @staticmethod
    def extract_links(text: str) -> list[str]:
        """
        Extract URLs from text.

        Args:
            text: Text to extract links from

        Returns:
            List of URLs found
        """
        url_pattern = r"https?://[^\s<>\[\]()\"']+"
        return re.findall(url_pattern, text)

    @classmethod
    def extract_job_links(cls, text: str) -> list[str]:
        """
        Extract job-related links from text.

        Args:
            text: Text to extract links from

        Returns:
            List of job platform URLs found
        """
        links = cls.extract_links(text)
        job_links = []
        for link in links:
            for domain in cls.JOB_DOMAINS:
                if domain in link.lower():
                    job_links.append(link)
                    break
        return job_links

    @staticmethod
    def normalize_link(url: str) -> str:
        """
        Normalize a URL for comparison (remove tracking parameters).

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        # Remove common tracking parameters
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        # Remove tracking params
        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "ref",
            "source",
            "fbclid",
            "gclid",
            "mc_cid",
            "mc_eid",
        }
        filtered_params = {
            k: v for k, v in params.items() if k.lower() not in tracking_params
        }

        # Rebuild URL
        new_query = urllib.parse.urlencode(filtered_params, doseq=True)
        normalized = urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, "")
        )

        return normalized.rstrip("/")

    @classmethod
    def same_job_link(cls, link1: str, link2: str) -> bool:
        """
        Check if two links point to the same job posting.

        Args:
            link1: First URL
            link2: Second URL

        Returns:
            True if they appear to be the same job
        """
        return cls.normalize_link(link1) == cls.normalize_link(link2)
