"""Basic bot command handlers: /start, /help, /status, /pause, /resume, /test."""

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.menu import main_menu

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)

router = Router()


def setup_commands_router(app: "BotApp") -> Router:
    """Setup commands router with app context."""

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        """Handle /start command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            await message.answer("This bot is private. Contact the owner for access.")
            return

        welcome_text = """
**Job Monitor Bot**

I monitor Telegram channels for job postings and alert you when I find matches for your CV.

Use the menu below to get started:
        """.strip()

        await message.answer(welcome_text, reply_markup=main_menu(), parse_mode="Markdown")

    @router.message(Command("menu"))
    async def cmd_menu(message: Message) -> None:
        """Handle /menu command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        await message.answer(
            "**Job Monitor Bot**\n\nSelect an option:",
            reply_markup=main_menu(),
            parse_mode="Markdown",
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        """Handle /help command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        help_text = """
**Job Monitor Bot Commands**

**CV Management:**
/setcv - Upload or paste your CV
/clearcv - Delete stored CV

**Channel Management:**
/addchannel <link> - Add channel to monitor
/removechannel <link> - Stop monitoring channel
/listchannels - Show monitored channels

**Filters:**
/setthreshold <0-100> - Set match score threshold
/addkeyword <word> - Add must-have keyword
/excludekeyword <word> - Exclude jobs with keyword
/setlocation <loc> - Set preferred location
/setremote <yes/no/any> - Set remote preference
/showfilters - Display current filters
/clearfilters - Reset all filters

**Control:**
/status - Show bot status
/pause - Pause monitoring
/resume - Resume monitoring
/test - Test with sample job

/help - Show this message
        """.strip()

        await message.answer(help_text, parse_mode="Markdown")

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        """Handle /status command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        try:
            stats = await app.db.get_stats()
            last_match = await app.db.get_last_match()
            threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))

            status_parts = [
                "**Bot Status**",
                "",
                f"Running: {'Yes' if app.is_running else 'No'}",
                f"Paused: {'Yes' if app.is_paused else 'No'}",
                f"CV Loaded: {'Yes' if app.cv_manager.has_cv else 'No'}",
                "",
                f"Channels: {stats.get('channels', 0)}",
                f"Messages Processed: {stats.get('processed', 0)}",
                f"Jobs Matched: {stats.get('matched', 0)}",
                f"Active Filters: {stats.get('filters', 0)}",
                "",
                f"Match Threshold: {threshold}%",
            ]

            if last_match:
                created = last_match.get("created_at", "Unknown")
                title = last_match.get("role_title", "Unknown")
                score = last_match.get("match_score", 0)
                status_parts.extend([
                    "",
                    f"Last Match: {title}",
                    f"Score: {score}%",
                    f"Time: {created}",
                ])

            await message.answer("\n".join(status_parts), parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            await message.answer(f"Error getting status: {e}")

    @router.message(Command("pause"))
    async def cmd_pause(message: Message) -> None:
        """Handle /pause command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        if app.is_paused:
            await message.answer("Bot is already paused.")
        else:
            app.is_paused = True
            await app.db.set_setting("paused", "true")
            await message.answer("Bot paused. Job monitoring is now disabled.")

    @router.message(Command("resume"))
    async def cmd_resume(message: Message) -> None:
        """Handle /resume command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        if not app.is_paused:
            await message.answer("Bot is already running.")
        else:
            app.is_paused = False
            await app.db.set_setting("paused", "false")
            await message.answer("Bot resumed. Job monitoring is now active.")

    @router.message(Command("test"))
    async def cmd_test(message: Message) -> None:
        """Handle /test command - test with a sample job post."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        if not app.cv_manager.has_cv:
            await message.answer("Please set your CV first with /setcv")
            return

        sample_job = """
Senior Python Developer @ TechCorp

We're hiring a Senior Python Developer to join our growing team!

Requirements:
- 5+ years Python experience
- Strong knowledge of Django or FastAPI
- Experience with PostgreSQL and Redis
- Familiar with Docker and Kubernetes
- Good communication skills

Nice to have:
- Machine learning experience
- AWS/GCP cloud experience

Location: Remote (US timezone)
Salary: $120k - $150k

Apply: https://techcorp.example.com/careers/python-dev
        """.strip()

        await message.answer("Testing with sample job post...")

        # Process the test job
        try:
            from core.models import TelegramMessage
            from datetime import datetime

            test_message = TelegramMessage(
                channel_id="test",
                channel_name="Test Channel",
                message_id=0,
                text=sample_job,
                date=datetime.now(),
            )

            await app.process_message(test_message, is_test=True)

        except Exception as e:
            logger.error(f"Error in test: {e}")
            await message.answer(f"Test failed: {e}")

    return router
