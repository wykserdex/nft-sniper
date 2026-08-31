"""Парсинг публичного HTML fragment.com — fallback-источник.

Публичные страницы fragment.com отдают серверный HTML с таблицей лотов
(``<tr class="tm-row-selectable">``): имя (``@name`` / ``+888 …``), статус
(``Resale``/…), цена в TON с разделителем тысяч (``35,504``) и время конца
аукциона (``<time datetime="…">``).

Парсер — чистая функция без I/O и без float (цены — Decimal → nanoTON int).
Вёрстка может меняться: на битой/изменённой разметке возвращается пустой
результат или строка пропускается — исключений не бывает (чёткая деградация,
ТЗ §7: «устойчивость к смене вёрстки»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from nftsniper.contexts.sources.domain.fragment import FragmentKind, FragmentStatus
from nftsniper.shared.money import NANO_PER_TON

_ROW_RE = re.compile(r'<tr class="tm-row-selectable">(.*?)</tr>', re.S)
_HREF_RE = re.compile(r'<a href="/(username|number)/([^"]+)"')
_NAME_RE = re.compile(r'class="table-cell-value tm-value">([^<]*)<')
_STATUS_RE = re.compile(r'class="table-cell-status-thin">([^<]*)<')
_PRICE_RE = re.compile(r'class="table-cell-value tm-value icon-before icon-ton">([^<]*)<')
_TIME_RE = re.compile(r'<time datetime="([^"]+)"')

_STATUS_MAP = {
    "resale": FragmentStatus.RESALE,
    "auction": FragmentStatus.ON_AUCTION,
    "on auction": FragmentStatus.ON_AUCTION,
    "for sale": FragmentStatus.FOR_SALE,
    "on sale": FragmentStatus.FOR_SALE,
    "sale": FragmentStatus.FOR_SALE,
    "sold": FragmentStatus.SOLD,
}


@dataclass(frozen=True, slots=True)
class ScrapedListing:
    """Одна строка лота, извлечённая из HTML."""

    name: str
    kind: FragmentKind
    price_nano: int | None
    ends_at: datetime | None
    status: FragmentStatus
    external_id: str


def parse_price_nano(text: str) -> int | None:
    """``35,504`` / ``3,756.5`` → nanoTON int; битое/отрицательное → None.

    Разделитель тысяч убирается, дробная часть — через Decimal (без float).
    """
    cleaned = text.replace(",", "").replace("\u00a0", "").strip()
    if not cleaned:
        return None
    try:
        ton = Decimal(cleaned)
    except InvalidOperation:
        return None
    if ton < 0:
        return None
    return int((ton * Decimal(NANO_PER_TON)).to_integral_value())


def parse_status(text: str) -> FragmentStatus:
    return _STATUS_MAP.get(text.strip().lower(), FragmentStatus.UNKNOWN)


def parse_end_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def kind_from_href(href: str, name: str) -> FragmentKind:
    """Тип актива: по URL (``/username/…``, ``/number/…``) либо по имени."""
    if href.startswith("number"):
        return FragmentKind.NUMBER
    if href.startswith("username"):
        return FragmentKind.USERNAME
    stripped = name.strip()
    if stripped.startswith("+"):
        return FragmentKind.NUMBER
    return FragmentKind.USERNAME


def _external_id(href: str, name: str) -> str:
    slug = href.split("/", 1)[-1] if href else ""
    if slug:
        return slug
    return re.sub(r"[+@\s]", "", name)


def parse_listings(html: str) -> list[ScrapedListing]:
    """Таблица лотов → список ``ScrapedListing`` (битые строки пропускаются)."""
    listings: list[ScrapedListing] = []
    for row in _ROW_RE.findall(html):
        name_match = _NAME_RE.search(row)
        if name_match is None:
            continue
        name = name_match.group(1).strip()
        if not name:
            continue
        href_match = _HREF_RE.search(row)
        href = href_match.group(1) if href_match else ""
        external_id = _external_id(href_match.group(2) if href_match else "", name)
        price_match = _PRICE_RE.search(row)
        price_nano = parse_price_nano(price_match.group(1)) if price_match else None
        time_match = _TIME_RE.search(row)
        ends_at = parse_end_time(time_match.group(1)) if time_match else None
        status_match = _STATUS_RE.search(row)
        status = parse_status(status_match.group(1)) if status_match else FragmentStatus.UNKNOWN
        listings.append(
            ScrapedListing(
                name=name,
                kind=kind_from_href(href, name),
                price_nano=price_nano,
                ends_at=ends_at,
                status=status,
                external_id=external_id,
            )
        )
    return listings
