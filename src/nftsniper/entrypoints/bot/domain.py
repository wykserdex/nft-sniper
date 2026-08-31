"""Настройки пользователя бота: value object + пороги.

Соответствует таблице ``user_settings`` из ТЗ §5 и мостится в
``AlertPolicy`` (alerts-контекст) для матчинга алертов.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from nftsniper.contexts.alerts.domain.alert import AlertPolicy
from nftsniper.entrypoints.bot.i18n import Lang
from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount


class SettingsValidationError(ValueError):
    """Пользователь ввёл некорректное значение в /settings."""


# Пороги по умолчанию (ТЗ §4): дискаунт 25%, confidence 0.5.
_DEFAULT_MIN_DISCOUNT = Decimal("0.25")
_DEFAULT_MIN_CONFIDENCE = Decimal("0.5")
_DEFAULT_MIN_LIQUIDITY = Decimal("0.2")
_DEFAULT_MAX_RISK = Decimal("0.7")
_DEFAULT_PRICE_MIN = Decimal("0")
_DEFAULT_PRICE_MAX = Decimal("10000")
_DEFAULT_MAX_ALERTS_PER_HOUR = 20

# Предвычисленные суммы (иммутабельны — можно переиспользовать как default'ы).
_PRICE_MIN_TON = TONAmount.from_ton(_DEFAULT_PRICE_MIN)
_PRICE_MAX_TON = TONAmount.from_ton(_DEFAULT_PRICE_MAX)


@dataclass(frozen=True, slots=True)
class UserSettings(ValueObject):
    """Настройки одного пользователя. Иммутабельны: изменение = новый объект."""

    user_id: str
    language: Lang = "ru"
    min_discount: Decimal = _DEFAULT_MIN_DISCOUNT  # 0..1
    min_confidence: Decimal = _DEFAULT_MIN_CONFIDENCE  # 0..1
    price_min: TONAmount = _PRICE_MIN_TON
    price_max: TONAmount = _PRICE_MAX_TON
    min_liquidity: Decimal = _DEFAULT_MIN_LIQUIDITY  # 0..1
    max_risk: Decimal = _DEFAULT_MAX_RISK  # 0..1
    max_alerts_per_hour: int = _DEFAULT_MAX_ALERTS_PER_HOUR
    paused: bool = False
    muted_collections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_discount",
            self._check_fraction(self.min_discount, "min_discount", strict=True),
        )
        object.__setattr__(
            self, "min_confidence", self._check_fraction(self.min_confidence, "min_confidence")
        )
        object.__setattr__(
            self, "min_liquidity", self._check_fraction(self.min_liquidity, "min_liquidity")
        )
        object.__setattr__(self, "max_risk", self._check_fraction(self.max_risk, "max_risk"))
        if self.price_min > self.price_max:
            msg = "price_min не может быть больше price_max"
            raise SettingsValidationError(msg)
        if self.max_alerts_per_hour < 1:
            msg = "max_alerts_per_hour должен быть >= 1"
            raise SettingsValidationError(msg)
        if self.language not in ("ru", "en"):
            msg = f"язык должен быть ru/en, получено {self.language!r}"
            raise SettingsValidationError(msg)

    @staticmethod
    def _check_fraction(value: Decimal, field: str, *, strict: bool = False) -> Decimal:
        lower = Decimal("0.000000001") if strict else Decimal(0)
        if not (lower <= value <= Decimal(1)):
            bounds = "(0, 1]" if strict else "[0, 1]"
            msg = f"{field} должен быть в {bounds}, получено {value}"
            raise SettingsValidationError(msg)
        return value

    def alert_policy(self) -> AlertPolicy:
        """Мостик в AlertPolicy для матчинга алертов."""
        return AlertPolicy(
            min_discount=self.min_discount,
            min_confidence=self.min_confidence,
            price_min=self.price_min,
            price_max=self.price_max,
            min_liquidity=self.min_liquidity,
            max_risk=self.max_risk,
            max_alerts_per_hour=self.max_alerts_per_hour,
        )

    def is_muted(self, collection_id: str) -> bool:
        return collection_id in self.muted_collections

    def with_update(self, field: str, raw: str) -> UserSettings:  # noqa: PLR0911 — диспетчер полей
        """Применить ввод пользователя к полю ``field`` (валидация + парсинг)."""
        value = raw.strip()
        if field == "min_discount":
            return replace(self, min_discount=self._parse_percent(value, "дискаунт"))
        if field == "min_confidence":
            return replace(self, min_confidence=self._parse_fraction(value, "confidence"))
        if field == "price_min":
            return replace(self, price_min=self._parse_ton(value, "мин. цена"))
        if field == "price_max":
            return replace(self, price_max=self._parse_ton(value, "макс. цена"))
        if field == "min_liquidity":
            return replace(self, min_liquidity=self._parse_fraction(value, "ликвидность"))
        if field == "max_risk":
            return replace(self, max_risk=self._parse_fraction(value, "риск"))
        if field == "language":
            return replace(self, language=self._parse_lang(value))
        msg = f"неизвестное поле настроек: {field}"
        raise SettingsValidationError(msg)

    def toggle_language(self) -> UserSettings:
        return replace(self, language="en" if self.language == "ru" else "ru")

    def toggle_pause(self) -> UserSettings:
        return replace(self, paused=not self.paused)

    def mute_collection(self, collection_id: str) -> UserSettings:
        if collection_id in self.muted_collections:
            return self
        return replace(self, muted_collections=(*self.muted_collections, collection_id))

    @staticmethod
    def _parse_percent(raw: str, label: str) -> Decimal:
        """ "25" или "25%" → 0.25; "0.25" тоже принимаем как долю."""
        text = raw.replace("%", "").strip()
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            msg = f"{label}: ожидалось число, получено {raw!r}"
            raise SettingsValidationError(msg) from exc
        if Decimal("0") < value <= Decimal("1"):
            return value  # введена доля
        if Decimal("1") < value <= Decimal("100"):
            return value / Decimal(100)
        msg = f"{label}: процент должен быть в (0, 100]"
        raise SettingsValidationError(msg)

    @staticmethod
    def _parse_fraction(raw: str, label: str) -> Decimal:
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            msg = f"{label}: ожидалось число 0..1, получено {raw!r}"
            raise SettingsValidationError(msg) from exc
        if not (Decimal(0) < value <= Decimal(1)):
            msg = f"{label}: значение должно быть в (0, 1]"
            raise SettingsValidationError(msg)
        return value

    @staticmethod
    def _parse_ton(raw: str, label: str) -> TONAmount:
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            msg = f"{label}: ожидалось число TON, получено {raw!r}"
            raise SettingsValidationError(msg) from exc
        if value < 0:
            msg = f"{label}: цена не может быть отрицательной"
            raise SettingsValidationError(msg)
        return TONAmount.from_ton(value)

    @staticmethod
    def _parse_lang(raw: str) -> Lang:
        text = raw.strip().lower()
        if text in ("ru", "рус", "ру"):
            return "ru"
        if text in ("en", "eng", "англ"):
            return "en"
        msg = f"язык: ожидалось ru/en, получено {raw!r}"
        raise SettingsValidationError(msg)


def default_settings(user_id: str, language: str | None) -> UserSettings:
    """Дефолтные настройки нового пользователя (язык — из Telegram, если ru/en)."""
    lang: Lang = "en" if language == "en" else "ru"
    return UserSettings(user_id=user_id, language=lang)
