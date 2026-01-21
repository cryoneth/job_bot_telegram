"""Telethon-based channel listener for monitoring Telegram channels."""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from telethon import TelegramClient, events
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    InviteHashInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Channel, Message

from core.models import TelegramMessage

logger = logging.getLogger(__name__)

MessageHandler = Callable[[TelegramMessage], None]


class ChannelListener:
    """Listens to multiple Telegram channels using Telethon MTProto client."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: str,
    ):
        """
        Initialize the channel listener.

        Args:
            api_id: Telegram API ID from my.telegram.org
            api_hash: Telegram API hash from my.telegram.org
            session_path: Path to store the Telethon session file
        """
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_path = session_path
        self._client: Optional[TelegramClient] = None
        self._message_handlers: list[MessageHandler] = []
        self._monitored_channels: set[str] = set()
        self._is_running = False
        self._message_queue: asyncio.Queue[TelegramMessage] = asyncio.Queue()

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._client is not None and self._client.is_connected()

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._is_running

    async def start(self) -> None:
        """Start the Telethon client and connect to Telegram."""
        if self._client is not None:
            return

        self._client = TelegramClient(
            self._session_path,
            self._api_id,
            self._api_hash,
        )

        await self._client.start()
        logger.info("Telethon client connected")

        # Register message handler for both incoming and outgoing messages
        @self._client.on(events.NewMessage(incoming=True, outgoing=True))
        async def handle_new_message(event: events.NewMessage.Event) -> None:
            await self._on_new_message(event)

        self._is_running = True
        logger.info(f"Monitoring channels: {self._monitored_channels}")

    async def stop(self) -> None:
        """Stop the client and disconnect."""
        self._is_running = False
        if self._client:
            await self._client.disconnect()
            self._client = None
            logger.info("Telethon client disconnected")

    def add_message_handler(self, handler: MessageHandler) -> None:
        """Add a handler to be called when new messages arrive."""
        self._message_handlers.append(handler)

    def remove_message_handler(self, handler: MessageHandler) -> None:
        """Remove a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    async def add_channel(self, channel_identifier: str) -> tuple[bool, str, Optional[str]]:
        """
        Add a channel to monitor.

        Args:
            channel_identifier: Channel username (e.g., @channel), ID, or invite link

        Returns:
            Tuple of (success, channel_id, channel_name or error message)
        """
        if not self._client:
            return False, "", "Client not connected"

        try:
            # Normalize the identifier
            identifier = self._normalize_channel_identifier(channel_identifier)

            # Get the channel entity
            entity = await self._client.get_entity(identifier)

            if isinstance(entity, Channel):
                channel_id = str(entity.id)
                channel_name = entity.title
                self._monitored_channels.add(channel_id)
                logger.info(f"Added channel: {channel_name} ({channel_id})")
                return True, channel_id, channel_name
            else:
                return False, "", "Not a channel"

        except UsernameInvalidError:
            return False, "", "Invalid username format"
        except UsernameNotOccupiedError:
            return False, "", "Channel not found"
        except ChannelInvalidError:
            return False, "", "Invalid channel"
        except ChannelPrivateError:
            return False, "", "Cannot access private channel (need to join first)"
        except InviteHashInvalidError:
            return False, "", "Invalid invite link"
        except FloodWaitError as e:
            return False, "", f"Rate limited. Try again in {e.seconds} seconds"
        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            return False, "", str(e)

    def remove_channel(self, channel_id: str) -> bool:
        """
        Remove a channel from monitoring.

        Args:
            channel_id: The channel ID to remove

        Returns:
            True if removed, False if not found
        """
        if channel_id in self._monitored_channels:
            self._monitored_channels.discard(channel_id)
            logger.info(f"Removed channel: {channel_id}")
            return True
        return False

    def set_monitored_channels(self, channel_ids: set[str]) -> None:
        """Set the complete list of monitored channels."""
        self._monitored_channels = channel_ids
        logger.info(f"Monitoring {len(channel_ids)} channels")

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        """Handle incoming messages from monitored channels."""
        if not self._is_running:
            return

        message: Message = event.message

        # Check if it's from a monitored channel
        if not message.peer_id:
            logger.debug("Message has no peer_id, skipping")
            return

        # Get channel ID (handle different peer types)
        channel_id = self._get_channel_id(message)

        if not channel_id:
            return

        if channel_id not in self._monitored_channels:
            return

        # Skip messages without text
        if not message.text:
            logger.debug("Message has no text, skipping")
            return

        logger.info(f"Processing message from {channel_id}: {message.text[:50]}...")

        try:
            # Get channel info
            chat = await event.get_chat()
            channel_name = getattr(chat, "title", None)

            # Create message object
            telegram_message = TelegramMessage(
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=message.id,
                text=message.text,
                date=message.date or datetime.now(),
                link=self._get_message_link(chat, message.id),
            )

            # Call handlers
            for handler in self._message_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(telegram_message)
                    else:
                        handler(telegram_message)
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _get_channel_id(self, message: Message) -> Optional[str]:
        """Extract channel ID from message."""
        peer = message.peer_id
        if hasattr(peer, "channel_id"):
            return str(peer.channel_id)
        elif hasattr(peer, "chat_id"):
            return str(peer.chat_id)
        return None

    def _get_message_link(self, chat: Channel, message_id: int) -> Optional[str]:
        """Generate message link."""
        if hasattr(chat, "username") and chat.username:
            return f"https://t.me/{chat.username}/{message_id}"
        elif hasattr(chat, "id"):
            return f"https://t.me/c/{chat.id}/{message_id}"
        return None

    def _normalize_channel_identifier(self, identifier: str) -> str:
        """Normalize channel identifier for Telethon."""
        identifier = identifier.strip()

        # Handle t.me links
        if "t.me/" in identifier:
            # Extract username or joinchat hash
            parts = identifier.split("t.me/")[-1].split("/")
            if parts[0] == "joinchat":
                return identifier  # Keep as invite link
            elif parts[0].startswith("+"):
                return identifier  # Keep as invite link
            else:
                return f"@{parts[0]}"

        # Handle @username format
        if identifier.startswith("@"):
            return identifier

        # Handle numeric IDs
        if identifier.lstrip("-").isdigit():
            return int(identifier)

        # Assume it's a username
        return f"@{identifier}"

    async def get_channel_info(self, channel_identifier: str) -> Optional[dict]:
        """Get information about a channel."""
        if not self._client:
            return None

        try:
            identifier = self._normalize_channel_identifier(channel_identifier)
            entity = await self._client.get_entity(identifier)

            if isinstance(entity, Channel):
                return {
                    "id": str(entity.id),
                    "title": entity.title,
                    "username": entity.username,
                    "participants_count": getattr(entity, "participants_count", None),
                }
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")

        return None

    async def run_until_disconnected(self) -> None:
        """Keep the client running until disconnected."""
        if self._client:
            await self._client.run_until_disconnected()
