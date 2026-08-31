"""Детекторы риска: чистые функции на доменных значениях.

Каждый детектор принимает явные входы и возвращает ``RiskFlag | None`` —
никакого I/O и float (только Decimal/str/datetime). Чистые функции дают
детерминированный скоринг, который можно гонять по подготовленному набору
скам-кейсов (критерий готовности: >= 90% при контролируемых ложных
срабатываниях, ТЗ §7).

Обязательные фильтры мусора (ТЗ §4):
- wash trading: кольцевые продажи между связанными кошельками;
- свежесозданные коллекции-клоны с похожим названием и подменённым символом;
- коллекции без реального объёма (3 продажи за месяц — не рынок);
- битые/пустые метаданные, недоступное медиа;
- явно завышенные fake-продажи в истории;
- аукционы против фиксированной цены;
- роялти и комиссия маркетплейса в реальном выходе.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from nftsniper.contexts.risk.domain.risk import RiskFlag, RiskSeverity
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount

# ── пороги по умолчанию (переопределяются в RiskConfig) ────────────────
DEFAULT_LOW_VOLUME_MIN_SALES = 3  # продаж за 30 дней (ТЗ §4)
DEFAULT_CLONE_SIMILARITY = Decimal("0.92")
DEFAULT_FRESH_SELLER_DAYS = 7
DEFAULT_FAKE_SALE_RATIO = Decimal("10")
DEFAULT_WASH_WINDOW = timedelta(days=2)
DEFAULT_WASH_MAX_CYCLE = 3
DEFAULT_ROYALTY_ALERT_RATIO = Decimal("0.80")  # net < 80% цены → флаг
_BPS_PER_UNIT = Decimal(10_000)
_PCT = Decimal(100)


# ── unicode-подмены (homoglyph) ────────────────────────────────────────

_CONFUSABLE_MAP: dict[str, str] = {
    # кириллица → латиница
    "а": "a",
    "в": "b",
    "е": "e",
    "ё": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ї": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "А": "a",
    "В": "b",
    "Е": "e",
    "Ё": "e",
    "К": "k",
    "М": "m",
    "Н": "h",
    "О": "o",
    "Р": "p",
    "С": "c",
    "Т": "t",
    "У": "y",
    "Х": "x",
    "І": "i",
    "Ј": "j",
    "Ѕ": "s",
    # греческий → латиница
    "α": "a",
    "β": "b",
    "γ": "y",
    "ε": "e",
    "η": "n",
    "ι": "i",
    "κ": "k",
    "μ": "m",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "σ": "s",
    "ς": "s",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "ω": "w",
    "ζ": "z",
}
_TRANSLATE = str.maketrans(_CONFUSABLE_MAP)


def normalize_confusables(name: str) -> str:
    """Имя → lowercase с заменой homoglyph-символов на латинские эквиваленты."""
    return name.lower().strip().translate(_TRANSLATE)


def detect_clone_collection(
    name: str,
    known_names: Sequence[str],
    *,
    similarity: Decimal = DEFAULT_CLONE_SIMILARITY,
) -> RiskFlag | None:
    """Клон/подмена: имя похоже на известное, но не совпадает точно (ТЗ §4)."""
    raw_lower = name.strip().lower()
    normalized = normalize_confusables(name)
    for known in known_names:
        if raw_lower == known.strip().lower():
            continue  # та же самая коллекция
        known_norm = normalize_confusables(known)
        if normalized == known_norm:
            return RiskFlag(
                code="CLONE_COLLECTION",
                severity=RiskSeverity.HIGH,
                message=f"Имя коллекции — подмена символов известной «{known}»",
            )
        ratio = Decimal(str(difflib.SequenceMatcher(None, normalized, known_norm).ratio()))
        if ratio >= similarity:
            return RiskFlag(
                code="CLONE_COLLECTION",
                severity=RiskSeverity.HIGH,
                message=(
                    f"Коллекция похожа на известную «{known}» "
                    f"(сходство {ratio.quantize(Decimal('0.01'))}) — возможный клон"
                ),
            )
    return None


# ── объём ──────────────────────────────────────────────────────────────


def detect_low_volume(
    sales_30d_count: int,
    *,
    min_sales: int = DEFAULT_LOW_VOLUME_MIN_SALES,
) -> RiskFlag | None:
    """Без реального объёма: < ``min_sales`` продаж за месяц — не рынок."""
    if sales_30d_count >= min_sales:
        return None
    return RiskFlag(
        code="LOW_VOLUME",
        severity=RiskSeverity.HIGH,
        message=f"Менее {min_sales} продаж за 30 дней — нет реального рынка",
    )


# ── метаданные и медиа ─────────────────────────────────────────────────


def detect_broken_metadata(
    item_name: str,
    *,
    media_available: bool | None = None,
) -> RiskFlag | None:
    """Пустое имя или недоступное медиа → битые метаданные (ТЗ §4)."""
    if not item_name.strip():
        return RiskFlag(
            code="BROKEN_METADATA",
            severity=RiskSeverity.HIGH,
            message="Пустые метаданные предмета",
        )
    if media_available is False:
        return RiskFlag(
            code="BROKEN_METADATA",
            severity=RiskSeverity.HIGH,
            message="Медиа предмета недоступно (IPFS/CDN)",
        )
    return None


# ── продавец ───────────────────────────────────────────────────────────


def detect_seller_risk(
    wallet: WalletInfo | None,
    *,
    now: datetime,
    min_age_days: int = DEFAULT_FRESH_SELLER_DAYS,
) -> RiskFlag | None:
    """Свежий/неизвестный продавец (ТЗ §4: возраст и история продавца)."""
    if wallet is None:
        return RiskFlag(
            code="UNKNOWN_SELLER",
            severity=RiskSeverity.MEDIUM,
            message="Продавец не найден on-chain",
        )
    created_at = wallet.created_at
    if created_at is None:
        return RiskFlag(
            code="UNKNOWN_SELLER",
            severity=RiskSeverity.MEDIUM,
            message="Возраст кошелька продавца неизвестен",
        )
    if now - created_at < timedelta(days=min_age_days):
        return RiskFlag(
            code="FRESH_SELLER",
            severity=RiskSeverity.HIGH,
            message=f"Кошелёк продавца создан менее {min_age_days} дней назад",
        )
    return None


# ── fake-продажи ───────────────────────────────────────────────────────


def median_price(sales: Sequence[SaleEvent]) -> TONAmount | None:
    """Медиана цен продаж (nearest-rank); пусто → None."""
    if not sales:
        return None
    ordered = sorted(sale.price for sale in sales)
    return ordered[len(ordered) // 2]


def detect_fake_sales(
    sales: Sequence[SaleEvent],
    *,
    ratio: Decimal = DEFAULT_FAKE_SALE_RATIO,
) -> RiskFlag | None:
    """Завышенные продажи: цена > ``ratio`` × медиана (накрутка fair price)."""
    median = median_price(sales)
    if median is None or median.is_zero:
        return None
    threshold = median.ton * ratio
    for sale in sales:
        if sale.price.ton > threshold:
            return RiskFlag(
                code="FAKE_SALES",
                severity=RiskSeverity.HIGH,
                message=(
                    f"Продажа {sale.price.formatted} TON в {ratio}× выше медианы "
                    f"{median.formatted} — вероятная накрутка"
                ),
            )
    return None


# ── wash trading (граф кошельков) ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WalletEdge:
    """Ребро графа кошельков: трансфер предмета из ``from_address`` в ``to_address``."""

    from_address: str
    to_address: str
    timestamp: datetime


def _has_short_cycle(adjacency: Mapping[str, Sequence[str]], max_len: int) -> bool:
    """Есть ли направленный цикл длины <= ``max_len`` в графе."""
    for start in adjacency:
        visited = {start}
        frontier = [start]
        for _ in range(max_len):
            next_frontier: list[str] = []
            for node in frontier:
                for neighbour in adjacency.get(node, ()):
                    if neighbour == start:
                        return True
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_frontier.append(neighbour)
            frontier = next_frontier
    return False


def detect_wash_trading(
    edges: Sequence[WalletEdge],
    *,
    now: datetime,
    window: timedelta = DEFAULT_WASH_WINDOW,
    max_cycle_len: int = DEFAULT_WASH_MAX_CYCLE,
) -> RiskFlag | None:
    """Кольцевые продажи: короткий цикл в графе кошельков предмета."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.from_address == edge.to_address:
            continue  # самому себе — не цикл
        if now - edge.timestamp > window:
            continue  # старые рёбра не считаем (контроль ложных срабатываний)
        adjacency[edge.from_address].append(edge.to_address)
    if _has_short_cycle(adjacency, max_cycle_len):
        return RiskFlag(
            code="WASH_TRADING",
            severity=RiskSeverity.HIGH,
            message="Кольцевые продажи между связанными кошельками — wash trading",
        )
    return None


# ── аукционы ───────────────────────────────────────────────────────────


def detect_auction_mismatch(is_auction: bool) -> RiskFlag | None:
    """Аукционная ставка ≠ фиксированная цена (ТЗ §4: сравнение типов)."""
    if not is_auction:
        return None
    return RiskFlag(
        code="AUCTION_MISMATCH",
        severity=RiskSeverity.MEDIUM,
        message="Аукцион: цена — текущая ставка, сравнение с fixed price некорректно",
    )


# ── роялти и комиссии (реальный выход) ─────────────────────────────────


def net_price(price: TONAmount, *, royalty_bps: int, marketplace_fee_bps: int) -> TONAmount:
    """Реальный выход: цена минус роялти и комиссия маркетплейса (ТЗ §4)."""
    if royalty_bps < 0 or marketplace_fee_bps < 0:
        msg = "базисные пункты не могут быть отрицательными"
        raise ValueError(msg)
    total_bps = Decimal(royalty_bps + marketplace_fee_bps)
    deduction = price.scale(total_bps / _BPS_PER_UNIT)
    net = price.sub(deduction)
    return net if net >= TONAmount.zero() else TONAmount.zero()


def detect_royalty_impact(
    price: TONAmount,
    *,
    royalty_bps: int,
    marketplace_fee_bps: int,
    alert_ratio: Decimal = DEFAULT_ROYALTY_ALERT_RATIO,
) -> RiskFlag | None:
    """Роялти+комиссия съедают заметную долю выхода (информационный флаг)."""
    if price.is_zero:
        return None
    net = net_price(price, royalty_bps=royalty_bps, marketplace_fee_bps=marketplace_fee_bps)
    ratio = net.ton / price.ton
    if ratio >= alert_ratio:
        return None
    impact_pct = ((Decimal(1) - ratio) * _PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return RiskFlag(
        code="ROYALTY_IMPACT",
        severity=RiskSeverity.LOW,
        message=(
            f"Роялти+комиссия съедают {int(impact_pct)}% — реальный выход {net.formatted} TON"
        ),
    )
