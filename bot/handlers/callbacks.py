"""Callback query handlers for inline keyboard buttons."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.menu import (
    main_menu,
    channels_menu,
    filters_menu,
    cv_menu,
    settings_menu,
    back_to_main_menu,
    confirm_action,
    remote_options,
    threshold_options,
    channel_list_keyboard,
    MENU_CHANNELS,
    MENU_FILTERS,
    MENU_CV,
    MENU_SETTINGS,
    MENU_STATUS,
)

if TYPE_CHECKING:
    from bot.app import BotApp

logger = logging.getLogger(__name__)


class InputStates(StatesGroup):
    """FSM states for user input."""
    waiting_for_channel = State()
    waiting_for_keyword = State()
    waiting_for_exclude = State()
    waiting_for_location = State()
    waiting_for_cv = State()
    waiting_for_test = State()


def setup_callbacks_router(app: "BotApp") -> Router:
    """Set up the callbacks router."""
    router = Router()

    # ===== Reply keyboard handlers (main menu buttons) =====

    @router.message(F.text == MENU_CHANNELS)
    async def menu_channels(message: Message):
        """Handle Channels button from reply keyboard."""
        channels = await app.db.get_channels()
        count = len(channels)
        await message.answer(
            f"**📡 Channel Management**\n\nCurrently monitoring {count} channel(s).",
            reply_markup=channels_menu(),
            parse_mode="Markdown",
        )

    @router.message(F.text == MENU_FILTERS)
    async def menu_filters(message: Message):
        """Handle Filters button from reply keyboard."""
        await message.answer(
            "**🎯 Filter Settings**\n\nCustomize which jobs match your preferences.",
            reply_markup=filters_menu(),
            parse_mode="Markdown",
        )

    @router.message(F.text == MENU_CV)
    async def menu_cv(message: Message):
        """Handle CV button from reply keyboard."""
        user_id = message.from_user.id if message.from_user else 0
        has_cv = app.matcher.has_cv(user_id)
        status = "✅ CV loaded" if has_cv else "❌ No CV uploaded"
        await message.answer(
            f"**📄 CV Management**\n\n{status}\n\nUpload your CV to enable job matching.",
            reply_markup=cv_menu(has_cv),
            parse_mode="Markdown",
        )

    @router.message(F.text == MENU_SETTINGS)
    async def menu_settings(message: Message):
        """Handle Settings button from reply keyboard."""
        user_id = message.from_user.id if message.from_user else 0
        threshold = await app.db.get_user_setting(user_id, "threshold")
        if not threshold:
            threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))
        await message.answer(
            f"**⚙️ Settings**\n\n"
            f"Match threshold: {threshold}/100\n"
            f"Status: {'⏸ Paused' if app.is_paused else '▶️ Running'}",
            reply_markup=settings_menu(app.is_paused),
            parse_mode="Markdown",
        )

    @router.message(F.text == MENU_STATUS)
    async def menu_status(message: Message):
        """Handle Status button from reply keyboard."""
        user_id = message.from_user.id if message.from_user else 0
        channels = await app.db.get_channels(active_only=True)
        threshold = await app.db.get_user_setting(user_id, "threshold")
        if not threshold:
            threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))

        status_lines = [
            "**📊 Bot Status**",
            "",
            f"Status: {'⏸ Paused' if app.is_paused else '✅ Running'}",
            f"Channels: {len(channels)} monitored",
            f"CV: {'✅ Loaded' if app.matcher.has_cv(user_id) else '❌ Not set'}",
            f"Threshold: {threshold}/100",
        ]

        await message.answer(
            "\n".join(status_lines),
            reply_markup=back_to_main_menu(),
            parse_mode="Markdown",
        )

    # ===== Inline callback handlers (for sub-menus) =====

    @router.callback_query(F.data == "menu:main")
    async def show_main_menu(callback: CallbackQuery):
        """Return to main menu (just acknowledge, reply keyboard is persistent)."""
        await callback.message.edit_text(
            "Use the menu below to navigate.",
            reply_markup=None,
        )
        await callback.answer()

    @router.callback_query(F.data == "menu:channels")
    async def show_channels_menu(callback: CallbackQuery):
        """Show channels management menu."""
        channels = await app.db.get_channels()
        count = len(channels)
        await callback.message.edit_text(
            f"**📡 Channel Management**\n\nCurrently monitoring {count} channel(s).",
            reply_markup=channels_menu(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "menu:filters")
    async def show_filters_menu(callback: CallbackQuery):
        """Show filters menu."""
        await callback.message.edit_text(
            "**🎯 Filter Settings**\n\nCustomize which jobs match your preferences.",
            reply_markup=filters_menu(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "menu:cv")
    async def show_cv_menu(callback: CallbackQuery):
        """Show CV management menu."""
        user_id = callback.from_user.id if callback.from_user else 0
        has_cv = app.matcher.has_cv(user_id)
        status = "✅ CV loaded" if has_cv else "❌ No CV uploaded"
        await callback.message.edit_text(
            f"**📄 CV Management**\n\n{status}\n\nUpload your CV to enable job matching.",
            reply_markup=cv_menu(has_cv),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "menu:settings")
    async def show_settings_menu(callback: CallbackQuery):
        """Show settings menu."""
        user_id = callback.from_user.id if callback.from_user else 0
        threshold = await app.db.get_user_setting(user_id, "threshold")
        if not threshold:
            threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))
        await callback.message.edit_text(
            f"**⚙️ Settings**\n\n"
            f"Match threshold: {threshold}/100\n"
            f"Status: {'⏸ Paused' if app.is_paused else '▶️ Running'}",
            reply_markup=settings_menu(app.is_paused),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "menu:status")
    async def show_status(callback: CallbackQuery):
        """Show bot status."""
        user_id = callback.from_user.id if callback.from_user else 0
        channels = await app.db.get_channels(active_only=True)
        threshold = await app.db.get_user_setting(user_id, "threshold")
        if not threshold:
            threshold = await app.db.get_setting("threshold", str(app.settings.match_threshold))

        status_lines = [
            "**📊 Bot Status**",
            "",
            f"Status: {'⏸ Paused' if app.is_paused else '✅ Running'}",
            f"Channels: {len(channels)} monitored",
            f"CV: {'✅ Loaded' if app.matcher.has_cv(user_id) else '❌ Not set'}",
            f"Threshold: {threshold}/100",
        ]

        await callback.message.edit_text(
            "\n".join(status_lines),
            reply_markup=back_to_main_menu(),
            parse_mode="Markdown",
        )
        await callback.answer()

    # --- Channel handlers ---

    @router.callback_query(F.data == "channels:add")
    async def add_channel_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user to add a channel."""
        await callback.message.edit_text(
            "**Add Channel**\n\n"
            "Send me the channel link or username:\n"
            "• `@channelname`\n"
            "• `https://t.me/channelname`\n"
            "• `https://t.me/+invitecode`\n"
            "• Channel ID (e.g., `-1001234567890`)\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_channel)
        await callback.answer()

    @router.callback_query(F.data == "channels:remove")
    async def remove_channel_prompt(callback: CallbackQuery):
        """Show channel list for removal."""
        channels = await app.db.get_channels()
        if not channels:
            await callback.message.edit_text(
                "No channels to remove.",
                reply_markup=back_to_main_menu(),
            )
        else:
            await callback.message.edit_text(
                "**Remove Channel**\n\nSelect a channel to remove:",
                reply_markup=channel_list_keyboard(channels),
                parse_mode="Markdown",
            )
        await callback.answer()

    @router.callback_query(F.data == "channels:list")
    async def list_channels(callback: CallbackQuery):
        """List all monitored channels."""
        channels = await app.db.get_channels()
        if not channels:
            text = "No channels monitored yet.\n\nUse ➕ Add Channel to start."
        else:
            lines = ["**Monitored Channels:**", ""]
            for ch in channels:
                name = ch.get("channel_name") or "Unknown"
                status = "✅" if ch.get("is_active") else "⏸"
                lines.append(f"{status} {name}")
            text = "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=channels_menu(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("rmchannel:"))
    async def remove_channel(callback: CallbackQuery):
        """Remove a specific channel."""
        channel_id = callback.data.split(":")[1]
        await app.db.remove_channel(channel_id)
        app.listener.remove_channel(channel_id)

        await callback.message.edit_text(
            f"✅ Channel removed.",
            reply_markup=channels_menu(),
        )
        await callback.answer("Channel removed")

    # --- Filter handlers ---

    @router.callback_query(F.data == "filters:add_keyword")
    async def add_keyword_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user to add a keyword."""
        await callback.message.edit_text(
            "**Add Required Keyword**\n\n"
            "Send me a keyword that jobs MUST contain:\n\n"
            "Example: `python`, `remote`, `senior`\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_keyword)
        await callback.answer()

    @router.callback_query(F.data == "filters:exclude_keyword")
    async def exclude_keyword_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user to add an excluded keyword."""
        await callback.message.edit_text(
            "**Add Excluded Keyword**\n\n"
            "Send me a keyword that should EXCLUDE jobs:\n\n"
            "Example: `unpaid`, `intern`, `junior`\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_exclude)
        await callback.answer()

    @router.callback_query(F.data == "filters:location")
    async def location_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user to set location."""
        await callback.message.edit_text(
            "**Set Location Preference**\n\n"
            "Send me your preferred location:\n\n"
            "Example: `San Francisco`, `Europe`, `USA`\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_location)
        await callback.answer()

    @router.callback_query(F.data == "filters:remote")
    async def remote_prompt(callback: CallbackQuery):
        """Show remote work options."""
        await callback.message.edit_text(
            "**Remote Work Preference**\n\n"
            "Do you prefer remote jobs?",
            reply_markup=remote_options(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("remote:"))
    async def set_remote(callback: CallbackQuery):
        """Set remote preference."""
        user_id = callback.from_user.id if callback.from_user else 0
        value = callback.data.split(":")[1]
        await app.db.set_filter("remote", value, user_id=user_id)
        await callback.message.edit_text(
            f"✅ Remote preference set to: {value}",
            reply_markup=filters_menu(),
        )
        await callback.answer("Saved")

    @router.callback_query(F.data == "filters:show")
    async def show_filters(callback: CallbackQuery):
        """Show current filters."""
        user_id = callback.from_user.id if callback.from_user else 0
        filters = await app.db.get_filters(user_id=user_id)
        if not filters:
            text = "No filters set.\n\nAdd some filters to customize your job matches."
        else:
            lines = ["**Current Filters:**", ""]
            for f in filters:
                ftype = f.get("filter_type", "")
                fval = f.get("filter_value", "")
                if ftype == "keyword":
                    lines.append(f"✅ Must have: {fval}")
                elif ftype == "excluded":
                    lines.append(f"🚫 Exclude: {fval}")
                elif ftype == "location":
                    lines.append(f"📍 Location: {fval}")
                elif ftype == "remote":
                    lines.append(f"🏠 Remote: {fval}")
                elif ftype == "seniority":
                    lines.append(f"📊 Level: {fval}")
            text = "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=filters_menu(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "filters:clear")
    async def clear_filters_confirm(callback: CallbackQuery):
        """Confirm clearing filters."""
        await callback.message.edit_text(
            "**Clear All Filters?**\n\n"
            "This will remove all your filter settings.",
            reply_markup=confirm_action("clear_filters"),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "confirm:clear_filters")
    async def clear_filters(callback: CallbackQuery):
        """Clear all filters."""
        user_id = callback.from_user.id if callback.from_user else 0
        await app.db.clear_filters(user_id=user_id)
        await callback.message.edit_text(
            "✅ All filters cleared.",
            reply_markup=filters_menu(),
        )
        await callback.answer("Filters cleared")

    # --- CV handlers ---

    @router.callback_query(F.data == "cv:upload")
    async def upload_cv_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user to upload CV."""
        await callback.message.edit_text(
            "**Upload CV**\n\n"
            "Send me your CV as:\n"
            "• Text message (paste your CV)\n"
            "• Text file (.txt)\n\n"
            "Your CV will be encrypted and stored securely.\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_cv)
        await callback.answer()

    @router.callback_query(F.data == "cv:clear")
    async def clear_cv_confirm(callback: CallbackQuery):
        """Confirm clearing CV."""
        await callback.message.edit_text(
            "**Clear CV?**\n\n"
            "This will delete your stored CV.",
            reply_markup=confirm_action("clear_cv"),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data == "confirm:clear_cv")
    async def clear_cv(callback: CallbackQuery):
        """Clear the CV."""
        user_id = callback.from_user.id if callback.from_user else 0
        app.cv_manager.clear_cv(user_id)
        app.matcher.clear_cv(user_id)
        await app.db.set_user_has_cv(user_id, False)
        await callback.message.edit_text(
            "✅ CV cleared.",
            reply_markup=cv_menu(False),
        )
        await callback.answer("CV cleared")

    # --- Settings handlers ---

    @router.callback_query(F.data == "settings:threshold")
    async def threshold_prompt(callback: CallbackQuery):
        """Show threshold options."""
        user_id = callback.from_user.id if callback.from_user else 0
        current = await app.db.get_user_setting(user_id, "threshold")
        if not current:
            current = await app.db.get_setting("threshold", str(app.settings.match_threshold))
        await callback.message.edit_text(
            f"**Set Match Threshold**\n\n"
            f"Current: {current}/100\n\n"
            f"Jobs scoring below this won't trigger alerts.",
            reply_markup=threshold_options(),
            parse_mode="Markdown",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("threshold:"))
    async def set_threshold(callback: CallbackQuery):
        """Set the threshold value."""
        user_id = callback.from_user.id if callback.from_user else 0
        value = callback.data.split(":")[1]
        await app.db.set_user_setting(user_id, "threshold", value)
        await callback.message.edit_text(
            f"✅ Threshold set to {value}/100",
            reply_markup=settings_menu(app.is_paused),
        )
        await callback.answer("Saved")

    @router.callback_query(F.data == "settings:pause")
    async def pause_bot(callback: CallbackQuery):
        """Pause the bot."""
        app.is_paused = True
        await app.db.set_setting("paused", "true")
        await callback.message.edit_text(
            "⏸ Bot paused.\n\nJob monitoring is temporarily stopped.",
            reply_markup=settings_menu(True),
        )
        await callback.answer("Paused")

    @router.callback_query(F.data == "settings:resume")
    async def resume_bot(callback: CallbackQuery):
        """Resume the bot."""
        app.is_paused = False
        await app.db.set_setting("paused", "false")
        await callback.message.edit_text(
            "▶️ Bot resumed.\n\nJob monitoring is active.",
            reply_markup=settings_menu(False),
        )
        await callback.answer("Resumed")

    @router.callback_query(F.data == "settings:test")
    async def test_prompt(callback: CallbackQuery, state: FSMContext):
        """Prompt user for test job text."""
        await callback.message.edit_text(
            "**Test Job Matching**\n\n"
            "Paste a job posting to test how it matches your CV:\n\n"
            "Send /cancel to cancel.",
            reply_markup=None,
            parse_mode="Markdown",
        )
        await state.set_state(InputStates.waiting_for_test)
        await callback.answer()

    return router
