"""TelegramNotifier: send/edit через фейковую сессию Bot API."""

import pytest
from aiogram import Bot

from nftsniper.contexts.alerts.adapters.telegram.notifier import (
    TelegramNotifier,
    build_inline_keyboard,
)
from nftsniper.contexts.alerts.domain.alert import AlertButton, AlertMessage
from tests.bot_helpers import TEST_TOKEN, FakeTelegramSession


@pytest.fixture
def bot_and_session() -> tuple[Bot, FakeTelegramSession]:
    session = FakeTelegramSession()
    bot = Bot(token=TEST_TOKEN, session=session)
    return bot, session


def test_build_inline_keyboard_mixed() -> None:
    keyboard = build_inline_keyboard(
        [
            AlertButton(text="✅ Взять", callback_data="dec:taken:al-1"),
            AlertButton(text="🔗 Открыть", url="https://getgems.io/nft/EQItem"),
        ]
    )
    rows = keyboard.inline_keyboard
    assert rows[0][0].callback_data == "dec:taken:al-1"
    assert rows[1][0].url == "https://getgems.io/nft/EQItem"


def test_alert_button_requires_exactly_one_payload() -> None:
    with pytest.raises(ValueError, match="ровно одно"):
        AlertButton(text="x")  # ни callback, ни url
    with pytest.raises(ValueError, match="ровно одно"):
        AlertButton(text="x", callback_data="a", url="https://x.io")


async def test_notifier_send_returns_message_id(
    bot_and_session: tuple[Bot, FakeTelegramSession],
) -> None:
    bot, session = bot_and_session
    notifier = TelegramNotifier(bot)

    message_id = await notifier.send(
        "123",
        AlertMessage(
            text="🔥 Deal 42%",
            buttons=(AlertButton(text="✅ Взять", callback_data="dec:taken:al-1"),),
        ),
    )

    assert message_id.isdigit()
    sent = session.sent_messages()[-1]
    assert sent.chat_id == 123
    assert sent.parse_mode == "HTML"
    assert sent.reply_markup is not None


async def test_notifier_edit(bot_and_session: tuple[Bot, FakeTelegramSession]) -> None:
    bot, session = bot_and_session
    notifier = TelegramNotifier(bot)

    await notifier.edit("123", "42", AlertMessage(text="❌ Скипнуто."))

    edited = session.edited_messages()[-1]
    assert edited.chat_id == 123
    assert edited.message_id == 42
    assert edited.text == "❌ Скипнуто."
