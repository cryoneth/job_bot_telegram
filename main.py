#!/usr/bin/env python3
"""
Job Monitor Bot - Entry Point

Monitors Telegram channels for job postings and alerts you
when they match your CV.

Usage:
    python main.py

Environment variables required:
    TELEGRAM_API_ID - from my.telegram.org
    TELEGRAM_API_HASH - from my.telegram.org
    BOT_TOKEN - from @BotFather
    OWNER_USER_ID - your Telegram user ID

Optional:
    CV_ENCRYPTION_KEY - auto-generated if not set
    MATCH_THRESHOLD - default 70
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from libraries
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


async def main() -> None:
    """Main entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Job Monitor Bot starting...")

    try:
        # Import here to ensure logging is set up first
        from config.settings import settings
        from bot.app import BotApp

        # Check for encryption key and generate if needed
        if not settings.cv_encryption_key:
            from core.encryption import CVEncryption

            key = CVEncryption.generate_key()
            logger.warning(
                "No CV_ENCRYPTION_KEY found. Generated new key.\n"
                "Add this to your .env file:\n"
                f"CV_ENCRYPTION_KEY={key}"
            )
            # Update settings with the new key
            settings.cv_encryption_key = key

        # Create and run the bot
        app = BotApp(settings)

        # Handle shutdown signals
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def signal_handler() -> None:
            logger.info("Shutdown signal received")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        # Start the bot
        await app.start()

        try:
            # Run both event loops concurrently
            bot_task = asyncio.create_task(
                app.dispatcher.start_polling(app.bot, handle_signals=False)
            )
            listener_task = asyncio.create_task(
                app.listener.run_until_disconnected()
            )
            shutdown_task = asyncio.create_task(shutdown_event.wait())

            # Wait for either shutdown signal or tasks to complete
            done, pending = await asyncio.wait(
                [bot_task, listener_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        finally:
            await app.stop()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Bot shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
