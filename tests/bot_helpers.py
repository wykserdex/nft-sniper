"""Хелперы для тестов бота: фейковая сессия Bot API + конструкторы апдейтов.

FakeTelegramSession перехватывает методы Telegram (sendMessage, editMessageText,
answerCallbackQuery) без сети и возвращает типизированные результаты, как в
реальном API. Конструкторы апдейтов собирают Message/CallbackQuery/Update для
``Dispatcher.feed_update``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.methods.base import TelegramMethod, TelegramType
from aiogram.types import CallbackQuery, Chat, Message, Update, User

TEST_TOKEN = "123456:TEST-TOKEN"


class FakeTelegramSession(BaseSession):
    """Сессия без сети: логирует вызовы и отдаёт фейковые результаты."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []
        self._counter = 100

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура из BaseSession
    ) -> TelegramType:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            self._counter += 1
            return cast(
                TelegramType,
                Message(
                    message_id=self._counter,
                    date=datetime.now(UTC),
                    chat=Chat(id=int(method.chat_id), type="private"),
                    text=method.text,
                ),
            )
        if isinstance(method, EditMessageText):
            return cast(
                TelegramType,
                Message(
                    message_id=int(method.message_id or 0),
                    date=datetime.now(UTC),
                    chat=Chat(id=int(method.chat_id or 0), type="private"),
                    text=method.text,
                ),
            )
        if isinstance(method, AnswerCallbackQuery):
            return cast(TelegramType, True)
        msg = f"неожиданный метод: {type(method).__name__}"
        raise NotImplementedError(msg)

    async def stream_content(  # type: ignore[override]
        self, *args: object, **kwargs: object
    ) -> object:
        msg = "stream_content не поддерживается в тестах"
        raise NotImplementedError(msg)

    async def close(self) -> None:
        return None

    # ── удобные выборки для ассертов ────────────────────────────────────

    def sent_messages(self) -> list[SendMessage]:
        return [c for c in self.calls if isinstance(c, SendMessage)]

    def edited_messages(self) -> list[EditMessageText]:
        return [c for c in self.calls if isinstance(c, EditMessageText)]

    @property
    def last_text(self) -> str:
        for call in reversed(self.calls):
            text = getattr(call, "text", None)
            if isinstance(text, str):
                return text
        return ""

    @property
    def last_chat_id(self) -> int:
        for call in reversed(self.calls):
            chat_id = getattr(call, "chat_id", None)
            if isinstance(chat_id, int):
                return chat_id
        return 0


def make_user(user_id: int = 123, language_code: str | None = "ru") -> User:
    return User(id=user_id, is_bot=False, first_name="Tester", language_code=language_code)


def make_chat(chat_id: int = 123) -> Chat:
    return Chat(id=chat_id, type="private")


def make_message(text: str, user: User | None = None, chat: Chat | None = None) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat if chat is not None else make_chat(),
        from_user=user if user is not None else make_user(),
        text=text,
    )


def make_callback(data: str, user: User | None = None, chat: Chat | None = None) -> CallbackQuery:
    return CallbackQuery(
        id="cb-1",
        from_user=user if user is not None else make_user(),
        chat_instance="ci-1",
        message=Message(
            message_id=10,
            date=datetime.now(UTC),
            chat=chat if chat is not None else make_chat(),
        ),
        data=data,
    )


def message_update(text: str, user: User | None = None) -> Update:
    return Update(update_id=1, message=make_message(text, user=user))


def callback_update(data: str, user: User | None = None) -> Update:
    return Update(update_id=2, callback_query=make_callback(data, user=user))
