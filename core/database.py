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
-- Monitored channels (shared across users)
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    channel_id TEXT UNIQUE NOT NULL,
    channel_name TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Processed messages (for deduplication - shared)
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

-- Job posts that matched (per user)
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

-- User filters/preferences (per user)
CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY,
    filter_type TEXT NOT NULL,
    filter_value TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User settings (per user)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Legacy settings (for backwards compatibility)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    has_cv BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        # Run migrations for existing databases
        await self._run_migrations()

        logger.info(f"Connected to database: {self.db_path}")

    async def _run_migrations(self) -> None:
        """Run database migrations for schema updates."""
        if not self._connection:
            return

        # Check if filters table has user_id column
        async with self._connection.execute("PRAGMA table_info(filters)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            if "user_id" not in columns:
                logger.info("Migrating filters table: adding user_id column")
                await self._connection.execute(
                    "ALTER TABLE filters ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0"
                )
                await self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_filters_user ON filters(user_id)"
                )
                await self._connection.commit()

        # Check if matched_jobs table has user_id column
        async with self._connection.execute("PRAGMA table_info(matched_jobs)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            if "user_id" not in columns:
                logger.info("Migrating matched_jobs table: adding user_id column")
                await self._connection.execute(
                    "ALTER TABLE matched_jobs ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0"
                )
                await self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_matched_jobs_user ON matched_jobs(user_id)"
                )
                await self._connection.commit()

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

    # Matched jobs operations (per user)
    async def add_matched_job(
        self,
        channel_id: str,
        message_id: int,
        match_score: int,
        raw_text: str,
        user_id: int = 0,
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
        """Add a matched job for a user. Returns the job ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                """INSERT INTO matched_jobs
                   (user_id, channel_id, message_id, role_title, company, location, is_remote,
                    seniority, salary_info, requirements, application_link,
                    match_score, match_reasons, filter_reasons, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
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

    async def get_recent_jobs(self, limit: int = 10, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Get recent matched jobs, optionally filtered by user."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        if user_id is not None:
            query = "SELECT * FROM matched_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, limit)
        else:
            query = "SELECT * FROM matched_jobs ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        async with self._connection.execute(query, params) as cursor:
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

    async def get_last_match(self, user_id: Optional[int] = None) -> Optional[dict[str, Any]]:
        """Get the most recent matched job, optionally for a specific user."""
        jobs = await self.get_recent_jobs(1, user_id)
        return jobs[0] if jobs else None

    # Filter operations (per user)
    async def add_filter(self, filter_type: str, filter_value: str, user_id: int = 0) -> int:
        """Add a filter. Returns the filter ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO filters (user_id, filter_type, filter_value) VALUES (?, ?, ?)",
                (user_id, filter_type, filter_value),
            )
            return cursor.lastrowid or 0

    async def set_filter(self, filter_type: str, filter_value: str, user_id: int = 0) -> int:
        """Set a filter (replaces existing of same type for user). Returns the filter ID."""
        async with self.transaction() as conn:
            # Remove existing filter of this type for user
            await conn.execute(
                "DELETE FROM filters WHERE user_id = ? AND filter_type = ?",
                (user_id, filter_type),
            )
            cursor = await conn.execute(
                "INSERT INTO filters (user_id, filter_type, filter_value) VALUES (?, ?, ?)",
                (user_id, filter_type, filter_value),
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
        self, filter_type: Optional[str] = None, active_only: bool = True, user_id: int = 0
    ) -> list[dict[str, Any]]:
        """Get filters for a user, optionally filtered by type."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        query = "SELECT * FROM filters WHERE user_id = ?"
        params: list[Any] = [user_id]
        if filter_type:
            query += " AND filter_type = ?"
            params.append(filter_type)
        if active_only:
            query += " AND is_active = TRUE"
        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_filters(self, user_id: int = 0) -> int:
        """Clear all filters for a user. Returns number of deleted filters."""
        async with self.transaction() as conn:
            cursor = await conn.execute("DELETE FROM filters WHERE user_id = ?", (user_id,))
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

    # Per-user settings operations
    async def get_user_setting(self, user_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a user-specific setting value."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else default

    async def set_user_setting(self, user_id: int, key: str, value: str) -> None:
        """Set a user-specific setting value."""
        async with self.transaction() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
                (user_id, key, value),
            )

    # User management
    async def get_or_create_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> dict[str, Any]:
        """Get or create a user record."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Try to get existing user
        async with self._connection.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # Update last_active
                await self._connection.execute(
                    "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (user_id,)
                )
                await self._connection.commit()
                return dict(row)

        # Create new user
        async with self.transaction() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                (user_id, username, first_name),
            )

        async with self._connection.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {"user_id": user_id}

    async def set_user_has_cv(self, user_id: int, has_cv: bool) -> None:
        """Update user's has_cv status."""
        async with self.transaction() as conn:
            await conn.execute(
                "UPDATE users SET has_cv = ? WHERE user_id = ?",
                (has_cv, user_id),
            )

    async def get_users_with_cv(self) -> list[dict[str, Any]]:
        """Get all users who have uploaded a CV."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute(
            "SELECT * FROM users WHERE has_cv = TRUE"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_all_users(self) -> list[dict[str, Any]]:
        """Get all registered users."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute("SELECT * FROM users") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

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
