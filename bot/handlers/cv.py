"""CV management handlers: /setcv, /clearcv."""

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)

router = Router()


class CVStates(StatesGroup):
    """States for CV input flow."""

    waiting_for_cv = State()


def setup_cv_router(app: "BotApp") -> Router:
    """Setup CV router with app context."""

    @router.message(Command("setcv"))
    async def cmd_set_cv(message: Message, state: FSMContext) -> None:
        """Handle /setcv command."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        # Check if CV text was provided with command
        if message.text and len(message.text) > 7:  # "/setcv " is 7 chars
            cv_text = message.text[7:].strip()
            if cv_text:
                await _save_cv(message, cv_text, app)
                return

        # Ask user to paste CV
        await state.set_state(CVStates.waiting_for_cv)
        await message.answer(
            "Please paste your CV text in the next message.\n\n"
            "Tips:\n"
            "- Include your skills, experience, and technologies\n"
            "- The more detailed, the better the matching\n"
            "- Your CV will be encrypted and stored securely\n\n"
            "Send /cancel to cancel.",
        )

    @router.message(CVStates.waiting_for_cv, F.text)
    async def handle_cv_input(message: Message, state: FSMContext) -> None:
        """Handle CV text input."""
        if message.from_user and not app.is_authorized(message.from_user.id):
            return

        if message.text == "/cancel":
            await state.clear()
            await message.answer("Cancelled.")
            return

        await _save_cv(message, message.text, app)
        await state.clear()

    @router.message(Command("clearcv"))
    async def cmd_clear_cv(message: Message) -> None:
        """Handle /clearcv command."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id
        if app.cv_manager.has_cv(user_id):
            app.cv_manager.clear_cv(user_id)
            app.matcher.clear_cv(user_id)
            await app.db.set_user_has_cv(user_id, False)
            await message.answer(
                "CV deleted.\n\n"
                "Set a new CV with /setcv to continue matching jobs.",
            )
        else:
            await message.answer("No CV is currently stored.")

    @router.message(Command("showcv"))
    async def cmd_show_cv(message: Message) -> None:
        """Handle /showcv command - show CV summary (not full text)."""
        if not message.from_user or not app.is_authorized(message.from_user.id):
            return

        user_id = message.from_user.id
        if not app.cv_manager.has_cv(user_id):
            await message.answer(
                "No CV stored.\n\nSet your CV with /setcv",
            )
            return

        summary = app.matcher.get_cv_summary(user_id)
        if not summary.get("loaded"):
            await message.answer("CV stored but not loaded into matcher.")
            return

        skills = summary.get("skills", [])
        skills_text = ", ".join(skills[:15]) if skills else "None identified"

        await message.answer(
            f"**CV Summary:**\n\n"
            f"Length: {summary.get('length', 0)} characters\n"
            f"Skills identified: {summary.get('skills_count', 0)}\n\n"
            f"**Skills preview:**\n{skills_text}"
            + ("..." if len(skills) > 15 else ""),
            parse_mode="Markdown",
        )

    return router


async def _save_cv(message: Message, cv_text: str, app: "BotApp") -> None:
    """Save CV and update matcher."""
    if not message.from_user:
        return

    user_id = message.from_user.id

    if len(cv_text) < 50:
        await message.answer(
            "CV text is too short. Please provide more details about "
            "your skills and experience.",
        )
        return

    if len(cv_text) > 50000:
        await message.answer(
            "CV text is too long. Please limit to 50,000 characters.",
        )
        return

    try:
        # Save encrypted CV for this user
        app.cv_manager.save_cv(cv_text, user_id)

        # Load into matcher for this user
        app.matcher.set_cv(cv_text, user_id)

        # Update database
        await app.db.set_user_has_cv(user_id, True)

        summary = app.matcher.get_cv_summary(user_id)
        skills_count = summary.get("skills_count", 0)

        await message.answer(
            f"CV saved and encrypted!\n\n"
            f"Length: {len(cv_text)} characters\n"
            f"Skills identified: {skills_count}\n\n"
            "Your CV will be used to match job posts. "
            "Add channels with /addchannel to start monitoring.",
        )
    except Exception as e:
        logger.error(f"Error saving CV for user {user_id}: {e}")
        await message.answer(f"Error saving CV: {e}")
