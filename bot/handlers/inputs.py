"""Input handlers for FSM states (waiting for user input)."""

from __future__ import annotations

import io
import logging
import re
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.handlers.callbacks import InputStates
from bot.menu import main_menu, channels_menu, filters_menu, cv_menu
from core.models import TelegramMessage

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Error extracting PDF text: {e}")
        raise


def setup_inputs_router(app: "BotApp") -> Router:
    """Set up the input handlers router."""
    router = Router()

    @router.message(F.text == "/cancel")
    async def cancel_input(message: Message, state: FSMContext):
        """Cancel any input state."""
        current_state = await state.get_state()
        if current_state:
            await state.clear()
            await message.answer(
                "Cancelled.\n\nSelect an option:",
                reply_markup=main_menu(),
            )
        else:
            await message.answer("Nothing to cancel.")

    @router.message(InputStates.waiting_for_channel)
    async def handle_channel_input(message: Message, state: FSMContext):
        """Handle channel input."""
        await state.clear()

        channel_input = message.text.strip()

        # Parse channel input
        channel_id = None
        channel_name = None

        # Check if it's a numeric ID
        if channel_input.lstrip("-").isdigit():
            channel_id = channel_input
        # Check for @username
        elif channel_input.startswith("@"):
            channel_name = channel_input[1:]
            try:
                entity = await app.listener._client.get_entity(channel_input)
                channel_id = str(entity.id)
                channel_name = getattr(entity, "title", channel_name)
            except Exception as e:
                await message.answer(
                    f"❌ Could not find channel: {e}\n\nTry using the channel ID instead.",
                    reply_markup=channels_menu(),
                )
                return
        # Check for t.me links
        elif "t.me/" in channel_input:
            try:
                entity = await app.listener._client.get_entity(channel_input)
                channel_id = str(entity.id)
                channel_name = getattr(entity, "title", None)
            except Exception as e:
                await message.answer(
                    f"❌ Could not join/find channel: {e}",
                    reply_markup=channels_menu(),
                )
                return
        else:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "• @channelname\n"
                "• https://t.me/channelname\n"
                "• Channel ID",
                reply_markup=channels_menu(),
            )
            return

        # Add channel
        await app.db.add_channel(channel_id, channel_name)
        app.listener.add_channel(channel_id)

        display_name = channel_name or channel_id
        await message.answer(
            f"✅ Added channel: {display_name}",
            reply_markup=channels_menu(),
        )

    @router.message(InputStates.waiting_for_keyword)
    async def handle_keyword_input(message: Message, state: FSMContext):
        """Handle required keyword input."""
        await state.clear()

        user_id = message.from_user.id if message.from_user else 0
        keyword = message.text.strip().lower()
        if len(keyword) < 2:
            await message.answer(
                "❌ Keyword too short.",
                reply_markup=filters_menu(),
            )
            return

        await app.db.set_filter("keyword", keyword, user_id=user_id)
        await message.answer(
            f"✅ Added required keyword: {keyword}",
            reply_markup=filters_menu(),
        )

    @router.message(InputStates.waiting_for_exclude)
    async def handle_exclude_input(message: Message, state: FSMContext):
        """Handle excluded keyword input."""
        await state.clear()

        user_id = message.from_user.id if message.from_user else 0
        keyword = message.text.strip().lower()
        if len(keyword) < 2:
            await message.answer(
                "❌ Keyword too short.",
                reply_markup=filters_menu(),
            )
            return

        await app.db.set_filter("excluded", keyword, user_id=user_id)
        await message.answer(
            f"✅ Added excluded keyword: {keyword}",
            reply_markup=filters_menu(),
        )

    @router.message(InputStates.waiting_for_location)
    async def handle_location_input(message: Message, state: FSMContext):
        """Handle location input."""
        await state.clear()

        user_id = message.from_user.id if message.from_user else 0
        location = message.text.strip()
        if len(location) < 2:
            await message.answer(
                "❌ Location too short.",
                reply_markup=filters_menu(),
            )
            return

        await app.db.set_filter("location", location, user_id=user_id)
        await message.answer(
            f"✅ Location set to: {location}",
            reply_markup=filters_menu(),
        )

    @router.message(InputStates.waiting_for_cv)
    async def handle_cv_input(message: Message, state: FSMContext):
        """Handle CV upload."""
        await state.clear()

        user_id = message.from_user.id if message.from_user else 0
        cv_text = None

        # Check for document
        if message.document:
            if message.document.file_size > 5 * 1024 * 1024:  # 5MB limit for PDFs
                await message.answer(
                    "❌ File too large. Max 5MB.",
                    reply_markup=cv_menu(app.matcher.has_cv(user_id)),
                )
                return

            try:
                file = await message.bot.get_file(message.document.file_id)
                file_obj = await message.bot.download_file(file.file_path)
                file_bytes = file_obj.read()

                # Check file type
                file_name = message.document.file_name or ""
                if file_name.lower().endswith(".pdf"):
                    cv_text = extract_text_from_pdf(file_bytes)
                else:
                    # Try to decode as text
                    cv_text = file_bytes.decode("utf-8")
            except Exception as e:
                await message.answer(
                    f"❌ Error reading file: {e}",
                    reply_markup=cv_menu(app.matcher.has_cv(user_id)),
                )
                return
        elif message.text:
            cv_text = message.text

        if not cv_text or len(cv_text) < 50:
            await message.answer(
                "❌ CV text too short. Please provide more details.",
                reply_markup=cv_menu(app.matcher.has_cv(user_id)),
            )
            return

        # Save encrypted CV for this user
        app.cv_manager.save_cv(cv_text, user_id)
        app.matcher.set_cv(cv_text, user_id)
        await app.db.set_user_has_cv(user_id, True)

        summary = app.matcher.get_cv_summary(user_id)
        skills_count = summary.get("skills_count", 0)

        await message.answer(
            f"✅ CV saved and encrypted!\n\n"
            f"Detected {skills_count} skills for matching.",
            reply_markup=cv_menu(True),
        )

    @router.message(InputStates.waiting_for_test)
    async def handle_test_input(message: Message, state: FSMContext):
        """Handle test job input."""
        await state.clear()

        user_id = message.from_user.id if message.from_user else 0

        if not app.matcher.has_cv(user_id):
            await message.answer(
                "❌ No CV set. Please upload your CV first.",
                reply_markup=main_menu(),
            )
            return

        test_text = message.text
        if len(test_text) < 20:
            await message.answer(
                "❌ Text too short for testing.",
                reply_markup=main_menu(),
            )
            return

        # Create a test message
        test_msg = TelegramMessage(
            channel_id="test",
            channel_name="Test",
            message_id=0,
            text=test_text,
            date=None,
            message_link="",
        )

        await message.answer("Processing...")
        await app.process_message(test_msg, is_test=True)

    return router
