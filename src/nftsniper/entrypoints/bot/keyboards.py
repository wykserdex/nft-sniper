"""Сборка inline-клавиатур (aiogram) для бота.

``build_inline_keyboard`` — из alerts-адаптера (кнопки алерта);
``settings_menu_keyboard`` — меню /settings.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nftsniper.contexts.alerts.adapters.telegram.notifier import build_inline_keyboard
from nftsniper.entrypoints.bot.i18n import get_strings

__all__ = ["build_inline_keyboard", "parse_setting_callback", "settings_menu_keyboard"]

#: Поля /settings → callback_data префикс (для FSM-хендлеров).
SETTING_CALLBACK_PREFIX = "set:"

SETTING_FIELDS = (
    "min_discount",
    "min_confidence",
    "price_min",
    "price_max",
    "min_liquidity",
    "max_risk",
)


def settings_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Меню /settings: по кнопке на каждое поле + язык + готово."""
    s = get_strings(lang)
    labels = {
        "min_discount": s.btn_edit_discount,
        "min_confidence": s.btn_edit_confidence,
        "price_min": s.btn_edit_price_min,
        "price_max": s.btn_edit_price_max,
        "min_liquidity": s.btn_edit_liquidity,
        "max_risk": s.btn_edit_risk,
    }
    rows: list[list[InlineKeyboardButton]] = []
    for field in SETTING_FIELDS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=labels[field], callback_data=f"{SETTING_CALLBACK_PREFIX}{field}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=s.btn_toggle_lang.format(value=lang.upper()),
                callback_data=f"{SETTING_CALLBACK_PREFIX}lang",
            ),
            InlineKeyboardButton(text=s.btn_done, callback_data=f"{SETTING_CALLBACK_PREFIX}done"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_setting_callback(data: str) -> str | None:
    """``set:{field}`` → field; ``set:lang`` → "lang"; ``set:done`` → "done"."""
    if not data.startswith(SETTING_CALLBACK_PREFIX):
        return None
    field = data[len(SETTING_CALLBACK_PREFIX) :]
    return field or None
