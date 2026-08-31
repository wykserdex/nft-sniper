"""Доставка алертов в Telegram: рендер сообщения + inline keyboard.

Кнопки: Взять / Скип / Следить / Мьют коллекции / Открыть на GetGems.
«Взять» не покупает: диплинк на маркетплейс + логирование интента.

- ``notifier.py`` — TelegramNotifier (NotifierPort) + build_inline_keyboard.
"""

from nftsniper.contexts.alerts.adapters.telegram.notifier import (
    TelegramNotifier,
    build_inline_keyboard,
)

__all__ = ["TelegramNotifier", "build_inline_keyboard"]
