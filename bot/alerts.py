"""Alert formatting and sending."""

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from core.models import JobPost, MatchResult, TelegramMessage

logger = logging.getLogger(__name__)


class AlertSender:
    """Formats and sends job match alerts."""

    def __init__(self, bot: Bot, owner_id: int):
        """
        Initialize the alert sender.

        Args:
            bot: aiogram Bot instance
            owner_id: Telegram user ID to send alerts to
        """
        self._bot = bot
        self._owner_id = owner_id

    async def send_job_alert(
        self,
        message: TelegramMessage,
        job_post: JobPost,
        match_result: MatchResult,
    ) -> bool:
        """
        Send a job match alert.

        Args:
            message: Original Telegram message
            job_post: Extracted job information
            match_result: Match scoring results

        Returns:
            True if sent successfully
        """
        alert_text = self._format_alert(message, job_post, match_result)

        try:
            await self._bot.send_message(
                chat_id=self._owner_id,
                text=alert_text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info(
                f"Alert sent: {job_post.summary} (score: {match_result.score})"
            )
            return True
        except TelegramAPIError as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def _format_alert(
        self,
        message: TelegramMessage,
        job_post: JobPost,
        match_result: MatchResult,
    ) -> str:
        """Format the alert message."""
        lines = []

        # Header with score
        score_emoji = self._get_score_emoji(match_result.score)
        lines.append(f"{score_emoji} **Job Match (Score: {match_result.score}/100)**")
        lines.append("")

        # Job title and company
        title_line = f"**{job_post.role_title or 'Job Posting'}**"
        if job_post.company:
            title_line += f" @ {job_post.company}"
        lines.append(title_line)
        lines.append("")

        # Match reasons
        if match_result.match_reasons:
            lines.append("**Why it matches:**")
            for reason in match_result.match_reasons[:3]:
                lines.append(f"• {reason}")
            lines.append("")

        # Job details
        details = []
        if job_post.location:
            location_text = job_post.location
            if job_post.is_remote:
                location_text += " (Remote)"
            details.append(f"📍 Location: {location_text}")
        elif job_post.is_remote:
            details.append("📍 Location: Remote")

        if job_post.seniority:
            details.append(f"📊 Level: {job_post.seniority.value.title()}")

        if job_post.salary_info:
            details.append(f"💰 Salary: {job_post.salary_info}")

        if details:
            lines.extend(details)
            lines.append("")

        # Application link
        if job_post.application_link:
            lines.append(f"🔗 [Apply Here]({job_post.application_link})")

        # Original message link
        lines.append(f"📨 [View on Telegram]({message.message_link})")

        # Filter reasons (if any)
        if match_result.filter_reasons:
            lines.append("")
            lines.append("⚠️ **Notes:**")
            for reason in match_result.filter_reasons[:2]:
                lines.append(f"• {reason}")

        # Channel info
        if message.channel_name:
            lines.append("")
            lines.append(f"_From: {message.channel_name}_")

        return "\n".join(lines)

    def _get_score_emoji(self, score: int) -> str:
        """Get emoji based on match score."""
        if score >= 90:
            return "🎯"
        elif score >= 80:
            return "✨"
        elif score >= 70:
            return "👍"
        elif score >= 60:
            return "📋"
        else:
            return "📝"

    async def send_test_result(
        self,
        job_post: JobPost,
        match_result: MatchResult,
    ) -> bool:
        """
        Send a test match result.

        Args:
            job_post: Test job post
            match_result: Match results

        Returns:
            True if sent successfully
        """
        lines = [
            "**Test Results:**",
            "",
            f"Score: {match_result.score}/100",
            f"Semantic Score: {match_result.semantic_score:.1f}/60",
            f"Keyword Score: {match_result.keyword_score:.1f}/25",
            "",
        ]

        if match_result.match_reasons:
            lines.append("**Match Reasons:**")
            for reason in match_result.match_reasons:
                lines.append(f"• {reason}")
            lines.append("")

        if match_result.filter_reasons:
            lines.append("**Penalties:**")
            for reason in match_result.filter_reasons:
                lines.append(f"• {reason}")
            lines.append("")

        if job_post.role_title:
            lines.append(f"**Detected Title:** {job_post.role_title}")
        if job_post.company:
            lines.append(f"**Detected Company:** {job_post.company}")
        if job_post.seniority:
            lines.append(f"**Detected Level:** {job_post.seniority.value}")

        try:
            await self._bot.send_message(
                chat_id=self._owner_id,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
            return True
        except TelegramAPIError as e:
            logger.error(f"Failed to send test result: {e}")
            return False

    async def send_notification(self, text: str) -> bool:
        """
        Send a simple notification message.

        Args:
            text: Message text

        Returns:
            True if sent successfully
        """
        try:
            await self._bot.send_message(
                chat_id=self._owner_id,
                text=text,
            )
            return True
        except TelegramAPIError as e:
            logger.error(f"Failed to send notification: {e}")
            return False
