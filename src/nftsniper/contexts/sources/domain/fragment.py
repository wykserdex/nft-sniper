"""Фрагмент: номера и юзернеймы Telegram (ТЗ §7).

Fragment — маркетплейс TON Foundation для Telegram-юзернеймов, анонимных
номеров и premium. Юзернеймы и номера — NFT в блокчейне TON, поэтому их
существование, имена, владельцы и реальные цены продаж читаются on-chain
(TonAPI / ChainPort); текущие ставки и цены аукционов — на fragment.com
(парсинг как fallback, ТЗ §3).

Правило ТЗ §3: «По Fragment: проверить ToS и robots.txt, ограничить частоту,
не логиниться под чужими сессиями. Если парсинг рискован — брать данные
Fragment-коллекций через on-chain индексер, там они тоже видны.»
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress


class FragmentKind(StrEnum):
    """Тип актива Fragment."""

    USERNAME = "username"
    NUMBER = "number"


class FragmentStatus(StrEnum):
    """Состояние лота на Fragment (из публичной выдачи)."""

    ON_AUCTION = "auction"
    FOR_SALE = "sale"
    RESALE = "resale"
    SOLD = "sold"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FragmentAsset(ValueObject):
    """Юзернейм или номер как NFT.

    ``address`` — on-chain адрес (raw ``0:hex``); ``name`` — человекочитаемое
    имя (``@blackhat`` / ``+888 0000 1312``); ``owner`` — текущий владелец
    (из on-chain), если известен.
    """

    address: str
    name: str
    kind: FragmentKind
    collection_id: str
    owner: TonAddress | None = None


@dataclass(frozen=True, slots=True)
class FragmentAuction(ValueObject):
    """Лот на Fragment: цена, статус, конец аукциона.

    ``price`` — текущая ставка (аукцион) или фиксированная цена; ``None``,
    если цена недоступна (деградация парсинга). ``seller`` — текущий владелец
    актива (из on-chain), может быть неизвестен.
    """

    asset: FragmentAsset
    price: TONAmount | None = None
    ends_at: datetime | None = None
    status: FragmentStatus = FragmentStatus.UNKNOWN
    external_id: str = ""
