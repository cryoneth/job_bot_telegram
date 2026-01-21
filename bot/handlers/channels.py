"""Channel management handlers: /addchannel, /removechannel, /listchannels."""

import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)

router = Router()


def setup_channels_router(app: "BotApp") -> Router:
    """Setup channels router with app context."""

    @router.message(Command("addchannel"))
    async def cmd_add_channel(message: Message, command: CommandObject) -> None:
        """Handle /addchannel command."""
        if message.from_user and message.from_user.id != app.owner_id:
            return

        if not command.args:
            await message.answer(
                "Usage: `/addchannel <channel>`\n\n"
                "Examples:\n"
                "- `/addchannel @channel_name`\n"
                "- `/addchannel https://t.me/channel_name`\n"
                "- `/addchannel -1001234567890`",
                parse_mode="Markdown",
            )
            return

        channel_identifier = command.args.strip()
        await message.answer(f"Adding channel: {channel_identifier}...")

        try:
            # Try to resolve the channel via Telethon
            success, channel_id, result = await app.listener.add_channel(channel_identifier)

            if success:
                # Save to database
                is_new = await app.db.add_channel(channel_id, result)
                if is_new:
                    await message.answer(
                        f"Added channel: **{result}**\n"
                        f"Channel ID: `{channel_id}`\n\n"
                        "Now monitoring for job posts!",
                        parse_mode="Markdown",
                    )
                else:
                    await message.answer(
                        f"Channel **{result}** is already being monitored.",
                        parse_mode="Markdown",
                    )
            else:
                await message.answer(f"Failed to add channel: {result}")

        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            await message.answer(f"Error: {e}")

    @router.message(Command("removechannel"))
    async def cmd_remove_channel(message: Message, command: CommandObject) -> None:
        """Handle /removechannel command."""
        if message.from_user and message.from_user.id != app.owner_id:
            return

        if not command.args:
            await message.answer(
                "Usage: `/removechannel <channel>`\n\n"
                "Use `/listchannels` to see monitored channels.",
                parse_mode="Markdown",
            )
            return

        channel_identifier = command.args.strip()

        try:
            # Get current channels to find the one to remove
            channels = await app.db.get_channels()

            # Try to match by name, username, or ID
            channel_to_remove = None
            for ch in channels:
                ch_id = ch.get("channel_id", "")
                ch_name = ch.get("channel_name", "")
                if (
                    channel_identifier.lstrip("@-") in ch_id
                    or channel_identifier.lower() in ch_name.lower()
                    or ch_id == channel_identifier
                ):
                    channel_to_remove = ch
                    break

            if channel_to_remove:
                channel_id = channel_to_remove["channel_id"]
                channel_name = channel_to_remove.get("channel_name", channel_id)

                # Remove from database
                await app.db.remove_channel(channel_id)

                # Remove from listener
                app.listener.remove_channel(channel_id)

                await message.answer(
                    f"Removed channel: **{channel_name}**",
                    parse_mode="Markdown",
                )
            else:
                await message.answer(
                    f"Channel not found: {channel_identifier}\n"
                    "Use `/listchannels` to see monitored channels.",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"Error removing channel: {e}")
            await message.answer(f"Error: {e}")

    @router.message(Command("listchannels"))
    async def cmd_list_channels(message: Message) -> None:
        """Handle /listchannels command."""
        if message.from_user and message.from_user.id != app.owner_id:
            return

        try:
            channels = await app.db.get_channels(active_only=False)

            if not channels:
                await message.answer(
                    "No channels are being monitored.\n\n"
                    "Add a channel with `/addchannel @channel_name`",
                    parse_mode="Markdown",
                )
                return

            lines = ["**Monitored Channels:**", ""]
            for ch in channels:
                name = ch.get("channel_name", "Unknown")
                ch_id = ch.get("channel_id", "")
                active = ch.get("is_active", True)
                status = "Active" if active else "Paused"
                lines.append(f"- {name} (`{ch_id}`) [{status}]")

            await message.answer("\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error listing channels: {e}")
            await message.answer(f"Error: {e}")

    return router
