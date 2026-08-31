"""Telegram-бот (aiogram 3) —.

Здесь появятся: handlers (/start, /settings с FSM, /watchlist, /stats, /mute,
/pause), обработка callback-кнопок, редактирование сообщения после решения,
диплинки на маркетплейс, локализация RU/EN.

Алерты открываются в Mini App (правки к ТЗ, §11):

    from aiogram.types import InlineKeyboardButton, WebAppInfo

    button = InlineKeyboardButton(
        text="🔥 Deal 42% — в приложении",
        web_app=WebAppInfo(url=f"{settings.webapp_url}/webapp/#nft/{item_id}"),
    )

Внутри мини-аппа — деталка NFT и оплата P2P-пересылкой в TON Keeper
(контекст contexts/otc, API /api/webapp, статика /webapp).
"""
