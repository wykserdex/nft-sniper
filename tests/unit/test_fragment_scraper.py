"""Юнит-тесты парсера fragment.com — чистые функции без I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nftsniper.contexts.sources.adapters.fragment.scraper import (
    parse_end_time,
    parse_listings,
    parse_price_nano,
    parse_status,
)
from nftsniper.contexts.sources.domain.fragment import FragmentKind, FragmentStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fragment"

NANO = 1_000_000_000


def test_parse_price_nano_thousands_separator() -> None:
    assert parse_price_nano("35,504") == 35_504 * NANO


def test_parse_price_nano_decimal() -> None:
    assert parse_price_nano("3,756.5") == 3_756_500_000_000
    assert parse_price_nano("0.5") == 500_000_000


def test_parse_price_nano_invalid() -> None:
    assert parse_price_nano("") is None
    assert parse_price_nano("abc") is None
    assert parse_price_nano("-5") is None
    assert parse_price_nano("--") is None


def test_parse_status_mapping() -> None:
    assert parse_status("Resale") is FragmentStatus.RESALE
    assert parse_status("Sold") is FragmentStatus.SOLD
    assert parse_status("For sale") is FragmentStatus.FOR_SALE
    assert parse_status("Auction") is FragmentStatus.ON_AUCTION
    assert parse_status("неизвестно") is FragmentStatus.UNKNOWN


def test_parse_end_time() -> None:
    parsed = parse_end_time("2026-09-24T07:43:28+00:00")
    assert parsed == datetime(2026, 9, 24, 7, 43, 28, tzinfo=UTC)
    assert parse_end_time("не дата") is None


def test_parse_usernames_listing() -> None:
    html = (FIXTURES / "usernames.html").read_text(encoding="utf-8")
    listings = parse_listings(html)
    assert len(listings) == 3
    first = listings[0]
    assert first.name == "@blackhat"
    assert first.kind is FragmentKind.USERNAME
    assert first.price_nano == 35_504 * NANO
    assert first.status is FragmentStatus.RESALE
    assert first.external_id == "blackhat"
    assert first.ends_at == datetime(2026, 9, 24, 7, 43, 28, tzinfo=UTC)


def test_parse_numbers_listing() -> None:
    html = (FIXTURES / "numbers.html").read_text(encoding="utf-8")
    listings = parse_listings(html)
    assert len(listings) == 3
    first = listings[0]
    assert first.name == "+888 0000 1312"
    assert first.kind is FragmentKind.NUMBER
    assert first.price_nano == 25_560 * NANO
    assert first.external_id == "88800001312"


def test_parse_listings_resilient_to_markup_change() -> None:
    """ТЗ §7: «устойчивость к смене вёрстки» — не падаем, отдаём пусто."""
    assert parse_listings("<html>совсем другая вёрстка</html>") == []
    assert parse_listings("") == []
    assert parse_listings('<tr class="tm-row-selectable">нет ячеек</tr>') == []


def test_parse_listings_skips_broken_rows() -> None:
    html = (
        '<tr class="tm-row-selectable"><td>битая строка без имени</td></tr>\n'
        '<tr class="tm-row-selectable"><td><div class="table-cell-value tm-value">@ok</div>'
        '<div class="table-cell-status-thin">Sold</div></td></tr>'
    )
    listings = parse_listings(html)
    assert len(listings) == 1
    assert listings[0].name == "@ok"
    assert listings[0].price_nano is None  # нет цены — не падаем
