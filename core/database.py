"""Async SQLite database wrapper."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
-- Monitored channels
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    channel_id TEXT UNIQUE NOT NULL,
    channel_name TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Processed messages (for deduplication)
CREATE TABLE IF NOT EXISTS processed_messages (
    id INTEGER PRIMARY KEY,
    channel_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_job_post BOOLEAN,
    match_score INTEGER,
    UNIQUE(channel_id, message_id)
);

-- Job posts that matched
CREATE TABLE IF NOT EXISTS matched_jobs (
    id INTEGER PRIMARY KEY,
    channel_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    role_title TEXT,
    company TEXT,
    location TEXT,
    is_remote BOOLEAN,
    seniority TEXT,
    salary_info TEXT,
    requirements TEXT,
    application_link TEXT,
    match_score INTEGER NOT NULL,
    match_reasons TEXT,
    filter_reasons TEXT,
    raw_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User filters/preferences
CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY,
    filter_type TEXT NOT NULL,
    filter_value TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_processed_messages_channel ON processed_messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_processed_messages_hash ON processed_messages(content_hash);
CREATE INDEX IF NOT EXISTS idx_processed_messages_date ON processed_messages(processed_at);
CREATE INDEX IF NOT EXISTS idx_matched_jobs_date ON matched_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_filters_type ON filters(filter_type);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Connect to the database and create schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager for database transactions."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        try:
            yield self._connection
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise

    # Channel operations
    async def add_channel(self, channel_id: str, channel_name: Optional[str] = None) -> bool:
        """Add a channel to monitor. Returns True if added, False if already exists."""
        try:
            async with self.transaction() as conn:
                await conn.execute(
                    "INSERT INTO channels (channel_id, channel_name) VALUES (?, ?)",
                    (channel_id, channel_name),
                )
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_channel(self, channel_id: str) -> bool:
        """Remove a channel from monitoring. Returns True if removed."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM channels WHERE channel_id = ?", (channel_id,)
            )
            return cursor.rowcount > 0

    async def get_channels(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Get all monitored channels."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        query = "SELECT * FROM channels"
        if active_only:
            query += " WHERE is_active = TRUE"
        async with self._connection.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def set_channel_active(self, channel_id: str, is_active: bool) -> bool:
        """Set channel active status."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "UPDATE channels SET is_active = ? WHERE channel_id = ?",
                (is_active, channel_id),
            )
            return cursor.rowcount > 0

    # Processed messages operations
    async def is_message_processed(self, channel_id: str, message_id: int) -> bool:
        """Check if a message has been processed."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute(
            "SELECT 1 FROM processed_messages WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def is_content_duplicate(
        self, content_hash: str, days: int = 7
    ) -> bool:
        """Check if content hash exists within the specified days."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        cutoff = datetime.now() - timedelta(days=days)
        async with self._connection.execute(
            "SELECT 1 FROM processed_messages WHERE content_hash = ? AND processed_at > ?",
            (content_hash, cutoff),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def add_processed_message(
        self,
        channel_id: str,
        message_id: int,
        content_hash: str,
        is_job_post: bool = False,
        match_score: Optional[int] = None,
    ) -> None:
        """Record a processed message."""
        async with self.transaction() as conn:
            await conn.execute(
                """INSERT OR IGNORE INTO processed_messages
                   (channel_id, message_id, content_hash, is_job_post, match_score)
                   VALUES (?, ?, ?, ?, ?)""",
                (channel_id, message_id, content_hash, is_job_post, match_score),
            )

    # Matched jobs operations
    async def add_matched_job(
        self,
        channel_id: str,
        message_id: int,
        match_score: int,
        raw_text: str,
        role_title: Optional[str] = None,
        company: Optional[str] = None,
        location: Optional[str] = None,
        is_remote: Optional[bool] = None,
        seniority: Optional[str] = None,
        salary_info: Optional[str] = None,
        requirements: Optional[str] = None,
        application_link: Optional[str] = None,
        match_reasons: Optional[list[str]] = None,
        filter_reasons: Optional[list[str]] = None,
    ) -> int:
        """Add a matched job. Returns the job ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                """INSERT INTO matched_jobs
                   (channel_id, message_id, role_title, company, location, is_remote,
                    seniority, salary_info, requirements, application_link,
                    match_score, match_reasons, filter_reasons, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    channel_id,
                    message_id,
                    role_title,
                    company,
                    location,
                    is_remote,
                    seniority,
                    salary_info,
                    requirements,
                    application_link,
                    match_score,
                    json.dumps(match_reasons) if match_reasons else None,
                    json.dumps(filter_reasons) if filter_reasons else None,
                    raw_text,
                ),
            )
            return cursor.lastrowid or 0

    async def get_recent_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent matched jobs."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute(
            "SELECT * FROM matched_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            jobs = []
            for row in rows:
                job = dict(row)
                if job.get("match_reasons"):
                    job["match_reasons"] = json.loads(job["match_reasons"])
                if job.get("filter_reasons"):
                    job["filter_reasons"] = json.loads(job["filter_reasons"])
                jobs.append(job)
            return jobs

    async def get_last_match(self) -> Optional[dict[str, Any]]:
        """Get the most recent matched job."""
        jobs = await self.get_recent_jobs(1)
        return jobs[0] if jobs else None

    # Filter operations
    async def add_filter(self, filter_type: str, filter_value: str) -> int:
        """Add a filter. Returns the filter ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO filters (filter_type, filter_value) VALUES (?, ?)",
                (filter_type, filter_value),
            )
            return cursor.lastrowid or 0

    async def remove_filter(self, filter_id: int) -> bool:
        """Remove a filter by ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM filters WHERE id = ?", (filter_id,)
            )
            return cursor.rowcount > 0

    async def get_filters(
        self, filter_type: Optional[str] = None, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """Get filters, optionally filtered by type."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        query = "SELECT * FROM filters WHERE 1=1"
        params: list[Any] = []
        if filter_type:
            query += " AND filter_type = ?"
            params.append(filter_type)
        if active_only:
            query += " AND is_active = TRUE"
        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_filters(self) -> int:
        """Clear all filters. Returns number of deleted filters."""
        async with self.transaction() as conn:
            cursor = await conn.execute("DELETE FROM filters")
            return cursor.rowcount

    # Settings operations
    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting value."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        """Set a setting value."""
        async with self.transaction() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    async def delete_setting(self, key: str) -> bool:
        """Delete a setting."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM settings WHERE key = ?", (key,)
            )
            return cursor.rowcount > 0

    # Cleanup operations
    async def cleanup_old_messages(self, days: int = 30) -> int:
        """Delete processed messages older than specified days."""
        cutoff = datetime.now() - timedelta(days=days)
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM processed_messages WHERE processed_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    # Stats
    async def get_stats(self) -> dict[str, int]:
        """Get database statistics."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        stats = {}
        queries = {
            "channels": "SELECT COUNT(*) FROM channels WHERE is_active = TRUE",
            "processed": "SELECT COUNT(*) FROM processed_messages",
            "matched": "SELECT COUNT(*) FROM matched_jobs",
            "filters": "SELECT COUNT(*) FROM filters WHERE is_active = TRUE",
        }
        for key, query in queries.items():
            async with self._connection.execute(query) as cursor:
                row = await cursor.fetchone()
                stats[key] = row[0] if row else 0
        return stats
