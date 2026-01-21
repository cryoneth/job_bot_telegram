"""Filter management handlers."""

import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from core.models import FilterType, RemotePreference, SeniorityLevel, UserFilters

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)

router = Router()


def setup_filters_router(app: "BotApp") -> Router:
    """Setup filters router with app context."""

    @router.message(Command("setthreshold"))
    async def cmd_set_threshold(message: Message, command: CommandObject) -> None:
        """Handle /setthreshold command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        if not command.args:
            current = await app.db.get_user_setting(user_id, "threshold")
            if not current:
                current = await app.db.get_setting("threshold", str(app.settings.match_threshold))
            await message.answer(
                f"Current threshold: **{current}%**\n\n"
                "Usage: `/setthreshold <0-100>`\n"
                "Jobs with match scores below this won't trigger alerts.",
                parse_mode="Markdown",
            )
            return

        try:
            threshold = int(command.args.strip())
            if not 0 <= threshold <= 100:
                raise ValueError("Must be 0-100")

            await app.db.set_user_setting(user_id, "threshold", str(threshold))
            await message.answer(
                f"Match threshold set to **{threshold}%**",
                parse_mode="Markdown",
            )

        except ValueError as e:
            await message.answer(f"Invalid value: {e}\nUse a number between 0 and 100.")

    @router.message(Command("addkeyword"))
    async def cmd_add_keyword(message: Message, command: CommandObject) -> None:
        """Handle /addkeyword command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        if not command.args:
            await message.answer(
                "Usage: `/addkeyword <word>`\n\n"
                "Add a must-have keyword. Jobs containing this will score higher.",
                parse_mode="Markdown",
            )
            return

        keyword = command.args.strip().lower()
        await app.db.add_filter(FilterType.KEYWORD.value, keyword, user_id=user_id)
        await message.answer(
            f"Added keyword: **{keyword}**\n"
            "Jobs containing this will score higher.",
            parse_mode="Markdown",
        )

    @router.message(Command("excludekeyword"))
    async def cmd_exclude_keyword(message: Message, command: CommandObject) -> None:
        """Handle /excludekeyword command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        if not command.args:
            await message.answer(
                "Usage: `/excludekeyword <word>`\n\n"
                "Jobs containing this keyword will be penalized.",
                parse_mode="Markdown",
            )
            return

        keyword = command.args.strip().lower()
        await app.db.add_filter(FilterType.EXCLUDED.value, keyword, user_id=user_id)
        await message.answer(
            f"Excluding keyword: **{keyword}**\n"
            "Jobs containing this will be penalized.",
            parse_mode="Markdown",
        )

    @router.message(Command("setlocation"))
    async def cmd_set_location(message: Message, command: CommandObject) -> None:
        """Handle /setlocation command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        if not command.args:
            await message.answer(
                "Usage: `/setlocation <location>`\n\n"
                "Examples:\n"
                "- `/setlocation New York`\n"
                "- `/setlocation Berlin`\n"
                "- `/setlocation Remote`",
                parse_mode="Markdown",
            )
            return

        location = command.args.strip()
        await app.db.add_filter(FilterType.LOCATION.value, location, user_id=user_id)
        await message.answer(
            f"Added preferred location: **{location}**",
            parse_mode="Markdown",
        )

    @router.message(Command("setremote"))
    async def cmd_set_remote(message: Message, command: CommandObject) -> None:
        """Handle /setremote command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        if not command.args:
            await message.answer(
                "Usage: `/setremote <yes|no|any>`\n\n"
                "- `yes` - Prefer remote positions\n"
                "- `no` - Prefer on-site positions\n"
                "- `any` - No preference (default)",
                parse_mode="Markdown",
            )
            return

        value = command.args.strip().lower()
        if value not in ("yes", "no", "any"):
            await message.answer("Invalid value. Use: yes, no, or any")
            return

        # Remove existing remote filter for this user
        filters = await app.db.get_filters(FilterType.REMOTE.value, user_id=user_id)
        for f in filters:
            await app.db.remove_filter(f["id"])

        # Add new remote preference
        await app.db.add_filter(FilterType.REMOTE.value, value, user_id=user_id)

        preference_text = {
            "yes": "remote positions",
            "no": "on-site positions",
            "any": "any work arrangement",
        }
        await message.answer(
            f"Remote preference set to: **{preference_text[value]}**",
            parse_mode="Markdown",
        )

    @router.message(Command("setseniority"))
    async def cmd_set_seniority(message: Message, command: CommandObject) -> None:
        """Handle /setseniority command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id
        valid_levels = [level.value for level in SeniorityLevel]

        if not command.args:
            levels_list = ", ".join(valid_levels)
            await message.answer(
                f"Usage: `/setseniority <level>`\n\n"
                f"Valid levels: {levels_list}\n\n"
                "Example: `/setseniority senior`",
                parse_mode="Markdown",
            )
            return

        level = command.args.strip().lower()
        if level not in valid_levels:
            await message.answer(
                f"Invalid level. Valid options: {', '.join(valid_levels)}"
            )
            return

        await app.db.add_filter(FilterType.SENIORITY.value, level, user_id=user_id)
        await message.answer(
            f"Added seniority preference: **{level}**",
            parse_mode="Markdown",
        )

    @router.message(Command("showfilters"))
    async def cmd_show_filters(message: Message) -> None:
        """Handle /showfilters command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        try:
            filters = await app.db.get_filters(user_id=user_id)
            threshold = await app.db.get_user_setting(user_id, "threshold")
            if not threshold:
                threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))

            if not filters and threshold == str(app.settings.match_threshold):
                await message.answer(
                    "No filters configured.\n\n"
                    "Available filter commands:\n"
                    "/setthreshold, /addkeyword, /excludekeyword,\n"
                    "/setlocation, /setremote, /setseniority",
                    parse_mode="Markdown",
                )
                return

            user_filters = UserFilters.from_db_filters(filters)
            user_filters.threshold = int(threshold)

            lines = ["**Current Filters:**", ""]
            lines.append(f"Match Threshold: {user_filters.threshold}%")

            if user_filters.keywords:
                lines.append(f"Required Keywords: {', '.join(user_filters.keywords)}")

            if user_filters.excluded:
                lines.append(f"Excluded Keywords: {', '.join(user_filters.excluded)}")

            if user_filters.locations:
                lines.append(f"Preferred Locations: {', '.join(user_filters.locations)}")

            if user_filters.seniorities:
                levels = [s.value for s in user_filters.seniorities]
                lines.append(f"Seniority Levels: {', '.join(levels)}")

            if user_filters.remote != RemotePreference.ANY:
                lines.append(f"Remote Preference: {user_filters.remote.value}")

            await message.answer("\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error showing filters: {e}")
            await message.answer(f"Error: {e}")

    @router.message(Command("clearfilters"))
    async def cmd_clear_filters(message: Message) -> None:
        """Handle /clearfilters command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id

        try:
            count = await app.db.clear_filters(user_id=user_id)
            # Reset user's threshold to default
            await app.db.set_user_setting(user_id, "threshold", str(app.settings.match_threshold))
            await message.answer(
                f"Cleared {count} filters.\n"
                f"Threshold reset to {app.settings.match_threshold}%.",
            )
        except Exception as e:
            logger.error(f"Error clearing filters: {e}")
            await message.answer(f"Error: {e}")

    return router
