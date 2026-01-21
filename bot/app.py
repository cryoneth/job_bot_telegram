"""Main bot application that orchestrates all components."""

import asyncio
import logging
import re
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import Settings
from core.database import Database
from core.encryption import CVEncryption, CVManager
from core.models import JobPost, TelegramMessage, UserFilters
from services.channel_listener import ChannelListener
from services.cv_matcher import CVMatcher
from services.deduplicator import Deduplicator
from services.job_classifier import JobClassifier
from services.web_scraper import WebScraper

from .alerts import AlertSender
from .handlers.callbacks import setup_callbacks_router
from .handlers.channels import setup_channels_router
from .handlers.commands import setup_commands_router
from .handlers.cv import setup_cv_router
from .handlers.filters import setup_filters_router
from .handlers.inputs import setup_inputs_router

logger = logging.getLogger(__name__)


class BotApp:
    """Main application that ties all components together."""

    def __init__(self, settings: Settings):
        """
        Initialize the bot application.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.settings.ensure_data_dir()

        # Initialize components
        self.db = Database(settings.db_path)
        self.encryption = CVEncryption(settings.cv_encryption_key)
        self.cv_manager = CVManager(self.encryption, settings.cv_path)
        self.listener = ChannelListener(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            session_path=str(settings.session_path),
        )
        self.deduplicator = Deduplicator(self.db)
        self.classifier = JobClassifier()
        self.matcher = CVMatcher()
        self.scraper = WebScraper()

        # Bot and dispatcher
        self.bot = Bot(token=settings.bot_token)
        self.dispatcher = Dispatcher(storage=MemoryStorage())
        self.alert_sender = AlertSender(self.bot, settings.owner_user_id)

        # State
        self.is_running = False
        self.is_paused = False
        self._owner_id = settings.owner_user_id

    @property
    def owner_id(self) -> int:
        """Get the owner's user ID."""
        return self._owner_id

    async def start(self) -> None:
        """Start the bot application."""
        logger.info("Starting Job Monitor Bot...")

        # Connect to database
        await self.db.connect()

        # Load paused state
        paused = await self.db.get_setting("paused", "false")
        self.is_paused = paused == "true"

        # Load CV if exists
        if self.cv_manager.has_cv:
            cv_text = self.cv_manager.get_cv()
            if cv_text:
                self.matcher.set_cv(cv_text)
                logger.info("CV loaded from storage")
            else:
                logger.warning("CV file exists but could not be decrypted - please re-upload with /setcv")
        else:
            logger.warning("No CV found - use /setcv to upload your CV")

        # Load monitored channels
        channels = await self.db.get_channels(active_only=True)
        channel_ids = {ch["channel_id"] for ch in channels}
        self.listener.set_monitored_channels(channel_ids)
        logger.info(f"Loaded {len(channel_ids)} monitored channels")

        # Start Telethon client
        await self.listener.start()

        # Register message handler
        self.listener.add_message_handler(self._on_channel_message)

        # Setup bot routers
        self._setup_routers()

        self.is_running = True
        logger.info("Bot started successfully")

    async def stop(self) -> None:
        """Stop the bot application."""
        logger.info("Stopping Job Monitor Bot...")
        self.is_running = False

        # Stop listener
        await self.listener.stop()

        # Close scraper
        await self.scraper.close()

        # Close database
        await self.db.close()

        # Close bot
        await self.bot.session.close()

        logger.info("Bot stopped")

    def _setup_routers(self) -> None:
        """Setup all command routers."""
        self.dispatcher.include_router(setup_commands_router(self))
        self.dispatcher.include_router(setup_callbacks_router(self))
        self.dispatcher.include_router(setup_inputs_router(self))
        self.dispatcher.include_router(setup_channels_router(self))
        self.dispatcher.include_router(setup_filters_router(self))
        self.dispatcher.include_router(setup_cv_router(self))

    async def _on_channel_message(self, message: TelegramMessage) -> None:
        """Handle incoming channel messages."""
        if self.is_paused:
            return

        await self.process_message(message)

    async def process_message(
        self, message: TelegramMessage, is_test: bool = False
    ) -> None:
        """
        Process a channel message through the job matching pipeline.

        Args:
            message: The message to process
            is_test: Whether this is a test (skip deduplication)
        """
        try:
            # 1. Deduplication check
            if not is_test and await self.deduplicator.is_duplicate(message):
                logger.info(f"Skipping duplicate message (already processed): {message.message_id}")
                return

            # 2. Check for URL-only messages and scrape first
            text_to_classify = message.text
            scraped_url = None
            is_job_url = False
            detected_job_url = None

            # Job URL patterns
            job_url_patterns = [
                'job', 'career', 'position', 'hiring', 'apply', 'vacancy',
                'gh_jid=', 'lever.co', 'greenhouse', 'workable', 'ashby',
                'breezy.hr', 'recruitee', 'smartrecruiters', 'posting'
            ]

            # If message is short and contains a URL, try scraping first
            if len(message.text.strip()) < 300:
                urls = re.findall(r'https?://[^\s<>\[\]()\"\']+', message.text)
                if urls:
                    for url in urls:
                        url_lower = url.lower()
                        if any(pattern in url_lower for pattern in job_url_patterns):
                            is_job_url = True
                            detected_job_url = url
                            logger.info(f"URL-only message detected, scraping: {url}")
                            try:
                                scraped_content = await self.scraper.scrape_job_url(url)
                                if scraped_content and scraped_content.get("full_text"):
                                    text_to_classify = scraped_content["full_text"]
                                    scraped_url = url
                                    logger.info(f"Scraped {len(text_to_classify)} chars from URL")
                                    break
                            except Exception as e:
                                logger.warning(f"Failed to scrape URL {url}: {e}")

            # 3. Job classification (using scraped content if available)
            is_job, keyword_count = self.classifier.is_job_post(text_to_classify)

            # Trust job URL patterns even if keyword detection fails
            if not is_job and is_job_url:
                logger.info(f"URL pattern indicates job post, bypassing keyword check (found {keyword_count})")
                is_job = True

            if not is_job:
                if not is_test:
                    await self.deduplicator.mark_processed(message, is_job_post=False)
                logger.info(f"Not a job post (only {keyword_count} keywords found, need 2+)")
                return

            # 4. Extract job information
            job_post = self.classifier.extract_job_post(text_to_classify)
            logger.info(f"Job post detected: {job_post.summary}")

            # Set the application link from the job URL
            if not job_post.application_link:
                if scraped_url:
                    job_post.application_link = scraped_url
                elif detected_job_url:
                    job_post.application_link = detected_job_url

            # 4.5. Scrape application link for more content (if not already scraped)
            if job_post.application_link and job_post.application_link != scraped_url:
                try:
                    enhanced_text = await self.scraper.get_enhanced_job_text(
                        job_post.application_link, text_to_classify
                    )
                    job_post.raw_text = enhanced_text
                except Exception as e:
                    logger.warning(f"Failed to scrape {job_post.application_link}: {e}")

            # 4. CV matching
            if not self.matcher.has_cv:
                logger.warning("No CV set - skipping job match. Use /setcv to upload your CV")
                if not is_test:
                    await self.deduplicator.mark_processed(
                        message, is_job_post=True, match_score=0
                    )
                return

            # Get user filters
            filters = await self._get_user_filters()

            # Match against CV
            match_result = self.matcher.match(job_post, filters)
            logger.info(f"Match score: {match_result.score}")

            # Mark as processed
            if not is_test:
                await self.deduplicator.mark_processed(
                    message, is_job_post=True, match_score=match_result.score
                )

            # 5. Threshold check
            threshold = int(
                await self.db.get_setting("threshold", str(self.settings.match_threshold))
            )

            if match_result.score >= threshold:
                # 6. Send alert
                if is_test:
                    await self.alert_sender.send_test_result(job_post, match_result)
                else:
                    await self.alert_sender.send_job_alert(
                        message, job_post, match_result
                    )

                    # Save to database
                    await self.db.add_matched_job(
                        channel_id=message.channel_id,
                        message_id=message.message_id,
                        match_score=match_result.score,
                        raw_text=message.text,
                        role_title=job_post.role_title,
                        company=job_post.company,
                        location=job_post.location,
                        is_remote=job_post.is_remote,
                        seniority=job_post.seniority.value if job_post.seniority else None,
                        salary_info=job_post.salary_info,
                        requirements=job_post.requirements,
                        application_link=job_post.application_link,
                        match_reasons=match_result.match_reasons,
                        filter_reasons=match_result.filter_reasons,
                    )
            elif is_test:
                await self.alert_sender.send_test_result(job_post, match_result)
                await self.alert_sender.send_notification(
                    f"Score {match_result.score} is below threshold {threshold}. "
                    "This job would not trigger an alert."
                )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    async def _get_user_filters(self) -> UserFilters:
        """Load user filters from database."""
        filters = await self.db.get_filters()
        user_filters = UserFilters.from_db_filters(filters)
        user_filters.threshold = int(
            await self.db.get_setting("threshold", str(self.settings.match_threshold))
        )
        return user_filters

    async def run(self) -> None:
        """Run the bot (blocking)."""
        await self.start()

        try:
            # Run both the Telethon client and aiogram dispatcher
            await asyncio.gather(
                self.dispatcher.start_polling(self.bot),
                self.listener.run_until_disconnected(),
            )
        finally:
            await self.stop()
