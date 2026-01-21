"""Interactive menu system with inline keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    """Create the main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton(text="📡 Channels", callback_data="menu:channels"),
            InlineKeyboardButton(text="🎯 Filters", callback_data="menu:filters"),
        ],
        [
            InlineKeyboardButton(text="📄 CV", callback_data="menu:cv"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="menu:settings"),
        ],
        [
            InlineKeyboardButton(text="📊 Status", callback_data="menu:status"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def channels_menu() -> InlineKeyboardMarkup:
    """Create the channels management menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Add Channel", callback_data="channels:add"),
            InlineKeyboardButton(text="➖ Remove Channel", callback_data="channels:remove"),
        ],
        [
            InlineKeyboardButton(text="📋 List Channels", callback_data="channels:list"),
        ],
        [
            InlineKeyboardButton(text="« Back", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def filters_menu() -> InlineKeyboardMarkup:
    """Create the filters management menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Add Keyword", callback_data="filters:add_keyword"),
            InlineKeyboardButton(text="🚫 Exclude Keyword", callback_data="filters:exclude_keyword"),
        ],
        [
            InlineKeyboardButton(text="📍 Set Location", callback_data="filters:location"),
            InlineKeyboardButton(text="🏠 Remote Pref", callback_data="filters:remote"),
        ],
        [
            InlineKeyboardButton(text="📋 Show Filters", callback_data="filters:show"),
            InlineKeyboardButton(text="🗑 Clear All", callback_data="filters:clear"),
        ],
        [
            InlineKeyboardButton(text="« Back", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def cv_menu(has_cv: bool = False) -> InlineKeyboardMarkup:
    """Create the CV management menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="📤 Upload CV", callback_data="cv:upload"),
        ],
    ]
    if has_cv:
        keyboard.append([
            InlineKeyboardButton(text="🗑 Clear CV", callback_data="cv:clear"),
        ])
    keyboard.append([
        InlineKeyboardButton(text="« Back", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def settings_menu(is_paused: bool = False) -> InlineKeyboardMarkup:
    """Create the settings menu."""
    pause_text = "▶️ Resume" if is_paused else "⏸ Pause"
    pause_data = "settings:resume" if is_paused else "settings:pause"

    keyboard = [
        [
            InlineKeyboardButton(text="🎚 Set Threshold", callback_data="settings:threshold"),
        ],
        [
            InlineKeyboardButton(text=pause_text, callback_data=pause_data),
        ],
        [
            InlineKeyboardButton(text="🧪 Test Match", callback_data="settings:test"),
        ],
        [
            InlineKeyboardButton(text="« Back", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def back_to_main_menu() -> InlineKeyboardMarkup:
    """Simple back button to main menu."""
    keyboard = [
        [InlineKeyboardButton(text="« Back to Menu", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def confirm_action(action: str) -> InlineKeyboardMarkup:
    """Confirmation buttons for destructive actions."""
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Yes", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ No", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def remote_options() -> InlineKeyboardMarkup:
    """Remote work preference options."""
    keyboard = [
        [
            InlineKeyboardButton(text="🏠 Remote Only", callback_data="remote:yes"),
            InlineKeyboardButton(text="🏢 On-site OK", callback_data="remote:no"),
        ],
        [
            InlineKeyboardButton(text="🤷 Any", callback_data="remote:any"),
        ],
        [
            InlineKeyboardButton(text="« Back", callback_data="menu:filters"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def threshold_options() -> InlineKeyboardMarkup:
    """Threshold value options."""
    keyboard = [
        [
            InlineKeyboardButton(text="50", callback_data="threshold:50"),
            InlineKeyboardButton(text="60", callback_data="threshold:60"),
            InlineKeyboardButton(text="70", callback_data="threshold:70"),
        ],
        [
            InlineKeyboardButton(text="80", callback_data="threshold:80"),
            InlineKeyboardButton(text="90", callback_data="threshold:90"),
        ],
        [
            InlineKeyboardButton(text="« Back", callback_data="menu:settings"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def channel_list_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    """Create keyboard with channel list for removal."""
    keyboard = []
    for ch in channels[:10]:  # Limit to 10 channels
        name = ch.get("channel_name") or ch.get("channel_id")
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {name[:30]}",
                callback_data=f"rmchannel:{ch['channel_id']}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="« Back", callback_data="menu:channels"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
