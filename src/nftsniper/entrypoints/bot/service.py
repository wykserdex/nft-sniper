"""BotService: логика бота без aiogram-типов, тестируема отдельно.

Хендлеры (handlers.py) — тонкая обёртка: достают аргументы из Telegram и
вызывают сервис; сервис зависит только от портов и домена. «Полный путь
настройки и реакции на алерт» проходится юнит-тестами на сервисе и
интеграционным тестом диспетчера (feed_update).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import AlertMessage, Decision
from nftsniper.entrypoints.bot.domain import (
    SettingsValidationError,
    UserSettings,
    default_settings,
)
from nftsniper.entrypoints.bot.i18n import get_strings
from nftsniper.entrypoints.bot.ports import (
    AlertRegistry,
    DecisionStore,
    UserSettingsStore,
    WatchlistStore,
)
from nftsniper.entrypoints.bot.render import (
    ACTION_MUTED,
    ACTION_SKIPPED,
    ACTION_TAKEN,
    ACTION_WATCH,
    AlertView,
    render_decision_popup,
)

# Поля /settings, доступные для редактирования (порядок в меню).
SETTING_FIELDS = (
    "min_discount",
    "min_confidence",
    "price_min",
    "price_max",
    "min_liquidity",
    "max_risk",
)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Итог нажатия кнопки алерта: чем редактировать сообщение и что всплывёт."""

    edited: AlertMessage
    popup: str
    action: str


class BotService:
    """Оркестрация команд и решений. Зависимости — порты (fake в тестах)."""

    def __init__(
        self,
        *,
        settings: UserSettingsStore,
        watchlist: WatchlistStore,
        decisions: DecisionStore,
        registry: AlertRegistry,
        clock: type[datetime] = datetime,
    ) -> None:
        self._settings = settings
        self._watchlist = watchlist
        self._decisions = decisions
        self._registry = registry
        self._clock = clock

    # ── команды ─────────────────────────────────────────────────────────

    async def start_text(self, user_id: str, language_code: str | None) -> str:
        strings = get_strings(self._lang(await self._load(user_id, language_code)))
        return strings.start

    async def help_text(self, user_id: str) -> str:
        settings = await self._load(user_id, None)
        return get_strings(settings.language).help

    async def settings_prompt(self, user_id: str) -> str:
        settings = await self._load(user_id, None)
        s = get_strings(settings.language)
        return s.settings_prompt.format(
            discount=s.settings_line_discount.format(value=int(settings.min_discount * 100)),
            confidence=s.settings_line_confidence.format(value=settings.min_confidence),
            price=s.settings_line_price.format(
                min=settings.price_min.formatted, max=settings.price_max.formatted
            ),
            liquidity=s.settings_line_liquidity.format(value=settings.min_liquidity),
            risk=s.settings_line_risk.format(value=settings.max_risk),
            lang=s.settings_line_lang.format(value=settings.language.upper()),
        )

    async def settings_saved_text(self, user_id: str) -> str:
        return get_strings((await self._load(user_id, None)).language).settings_saved

    async def lang(self, user_id: str) -> str:
        """Текущий язык пользователя (для клавиатур)."""
        return (await self._load(user_id, None)).language

    async def ask_field_text(self, user_id: str, field: str) -> str:
        s = get_strings((await self._load(user_id, None)).language)
        prompts = {
            "min_discount": s.ask_discount,
            "min_confidence": s.ask_confidence,
            "price_min": s.ask_price_min,
            "price_max": s.ask_price_max,
            "min_liquidity": s.ask_liquidity,
            "max_risk": s.ask_risk,
        }
        return prompts.get(field, s.ask_discount)

    async def apply_setting(self, user_id: str, field: str, raw: str) -> tuple[bool, str]:
        """Применить ввод: (успех, текст ответа). Ошибка → текст с пояснением."""
        settings = await self._load(user_id, None)
        s = get_strings(settings.language)
        try:
            updated = settings.with_update(field, raw)
        except SettingsValidationError as exc:
            return False, s.bad_value.format(error=str(exc))
        await self._settings.save(updated)
        return True, await self.settings_prompt(user_id)

    async def toggle_language(self, user_id: str) -> str:
        settings = await self._load(user_id, None)
        await self._settings.save(settings.toggle_language())
        return await self.settings_prompt(user_id)

    async def watchlist_text(self, user_id: str) -> str:
        s = get_strings((await self._load(user_id, None)).language)
        items = await self._watchlist.list(user_id)
        if not items:
            return s.watchlist_empty
        lines = [s.watchlist_title] + [s.watchlist_line.format(item=item) for item in items]
        return "\n".join(lines)

    async def mute_text(self, user_id: str) -> str:
        s = get_strings((await self._load(user_id, None)).language)
        muted = (await self._load(user_id, None)).muted_collections
        if not muted:
            return s.mute_empty
        lines = [s.mute_title] + [s.mute_line.format(collection=c) for c in muted]
        return "\n".join(lines)

    async def pause(self, user_id: str, *, paused: bool) -> str:
        settings = await self._load(user_id, None)
        s = get_strings(settings.language)
        if settings.paused == paused:
            return s.no_change
        await self._settings.save(
            UserSettings(
                user_id=user_id,
                language=settings.language,
                min_discount=settings.min_discount,
                min_confidence=settings.min_confidence,
                price_min=settings.price_min,
                price_max=settings.price_max,
                min_liquidity=settings.min_liquidity,
                max_risk=settings.max_risk,
                max_alerts_per_hour=settings.max_alerts_per_hour,
                quiet_hours=settings.quiet_hours,
                paused=paused,
                muted_collections=settings.muted_collections,
            )
        )
        return s.paused if paused else s.resumed

    async def stats_text(self, user_id: str) -> str:
        s = get_strings((await self._load(user_id, None)).language)
        counts = await self._decisions.count_by_user(user_id)
        sent = sum(counts.values())
        if sent == 0:
            return s.no_stats
        taken = counts.get("taken", 0)
        rate = Decimal(taken * 100) / Decimal(sent)
        return s.stats_lines.format(
            sent=sent,
            taken=taken,
            skipped=counts.get("skipped", 0),
            rate=int(rate),
            paused=counts.get("paused", 0),
        )

    # ── решения по алерту ───────────────────────────────────────────────

    async def register_alert(self, view: AlertView) -> None:
        """Запомнить контекст алерта (для диплинков/вотчлиста/мьюта)."""
        await self._registry.put(view.alert_id, _view_to_context(view))

    async def handle_decision(
        self,
        user_id: str,
        action: str,
        alert_id: str,
        *,
        latency_ms: int,
    ) -> DecisionResult:
        """Обработать нажатие кнопки алерта; записать Decision (ТЗ §6)."""
        if action not in (ACTION_TAKEN, ACTION_SKIPPED, ACTION_WATCH, ACTION_MUTED):
            settings = await self._load(user_id, None)
            return DecisionResult(
                edited=AlertMessage(text=get_strings(settings.language).decided_unknown),
                popup="",
                action=action,
            )
        await self._decisions.save(
            Decision(
                id=uuid.uuid4().hex,
                alert_id=alert_id,
                user_id=user_id,
                action=action,
                latency_ms=latency_ms,
                created_at=self._clock.now(UTC),
            )
        )
        context = await self._registry.get(alert_id)
        settings = await self._load(user_id, None)

        if action == ACTION_TAKEN:
            link = _get_link(context)
            edited = AlertMessage(
                text=get_strings(settings.language).decided_taken.format(link=link)
            )
            return DecisionResult(
                edited=edited, popup=render_decision_popup(action, settings.language), action=action
            )

        if action == ACTION_SKIPPED:
            return DecisionResult(
                edited=AlertMessage(text=get_strings(settings.language).decided_skipped),
                popup="",
                action=action,
            )

        if action == ACTION_WATCH:
            item_id = _get_item_id(context)
            if item_id:
                await self._watchlist.add(user_id, item_id)
            return DecisionResult(
                edited=AlertMessage(text=get_strings(settings.language).decided_watch),
                popup="",
                action=action,
            )

        collection_id = _get_collection_id(context)
        if collection_id:
            updated = settings.mute_collection(collection_id)
            await self._settings.save(updated)
        return DecisionResult(
            edited=AlertMessage(text=get_strings(settings.language).decided_muted),
            popup="",
            action=action,
        )

    # ── внутренние ──────────────────────────────────────────────────────

    async def _load(self, user_id: str, language_code: str | None) -> UserSettings:
        stored = await self._settings.get(user_id)
        if stored is not None:
            return stored
        created = default_settings(user_id, language_code)
        await self._settings.save(created)
        return created

    def _lang(self, settings: UserSettings) -> str:
        return settings.language


def _view_to_context(view: AlertView) -> dict[str, object]:
    return {
        "item_id": view.item_id,
        "item_name": view.item_name,
        "collection_id": view.collection_id,
        "collection_name": view.collection_name,
        "getgems_url": view.getgems_url,
    }


def _get_link(context: dict[str, object] | None) -> str:
    if context is None:
        return ""
    return str(context.get("getgems_url") or context.get("item_id") or "")


def _get_item_id(context: dict[str, object] | None) -> str | None:
    if context is None:
        return None
    value = context.get("item_id")
    return str(value) if value else None


def _get_collection_id(context: dict[str, object] | None) -> str | None:
    if context is None:
        return None
    value = context.get("collection_id")
    return str(value) if value else None
