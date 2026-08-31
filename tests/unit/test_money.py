"""Деньги (критерий приёмки): TON/nanoTON/USD на Decimal, float запрещён."""

from decimal import Decimal

import pytest

from nftsniper.shared.money import (
    NANO_PER_TON,
    MoneyError,
    TONAmount,
    USDAmount,
    USDRate,
    format_ton,
    format_usd,
)

D = Decimal


def test_from_ton_and_nano_roundtrip() -> None:
    assert TONAmount.from_ton(D("120")).nano == 120 * NANO_PER_TON
    assert TONAmount.from_nano(120 * NANO_PER_TON).ton == D("120")
    assert TONAmount.from_nano(1).ton == D("0.000000001")
    assert TONAmount.from_ton(0) == TONAmount.from_nano(0)


def test_int_accepted_as_whole_ton() -> None:
    assert TONAmount.from_ton(5).ton == D("5")
    assert TONAmount.from_nano(2 * NANO_PER_TON).ton == D("2")


def test_float_rejected() -> None:
    with pytest.raises(MoneyError, match="float запрещён"):
        TONAmount.from_ton(1.5)  # type: ignore[arg-type]
    with pytest.raises(MoneyError, match="float запрещён"):
        TONAmount(ton=0.1)  # type: ignore[arg-type]


def test_more_than_9_decimals_rejected() -> None:
    with pytest.raises(MoneyError, match="9 знаков"):
        TONAmount.from_ton(D("0.0000000001"))
    with pytest.raises(MoneyError, match="9 знаков"):
        TONAmount.from_ton(D("1.1234567891"))


def test_bool_rejected() -> None:
    # bool — подтип int в mypy, поэтому отлавливается runtime-защитой
    with pytest.raises(MoneyError):
        TONAmount.from_ton(True)
    with pytest.raises(MoneyError):
        TONAmount.from_nano(1.0)  # type: ignore[arg-type]


def test_add_sub() -> None:
    a = TONAmount.from_ton(D("120"))
    b = TONAmount.from_nano(123_456_789)
    assert (a + b).formatted == "120.123456789"
    assert (b - a).formatted == "-119.876543211"
    assert a.add(b) == a + b
    assert b.sub(a) == b - a
    assert (-a).formatted == "-120"
    assert (-a).abs().formatted == "120"


def test_ordering_and_hash() -> None:
    a = TONAmount.from_ton(1)
    b = TONAmount.from_ton(2)
    a_copy = TONAmount.from_nano(NANO_PER_TON)
    assert a < b
    assert b > a
    assert a <= a_copy
    assert a >= a_copy
    assert a != b
    assert hash(a) == hash(a_copy)
    assert {a, a_copy} == {a}


def test_scale() -> None:
    assert TONAmount.from_ton(D("200")).scale(D("0.75")).formatted == "150"
    assert TONAmount.from_ton(D("1")).scale(D("0.123456789")).formatted == "0.123456789"
    # округление до nanoTON
    assert TONAmount.from_ton(D("1")).scale(D("0.3333333333")).formatted == "0.333333333"


def test_usd_conversion_roundtrip() -> None:
    rate = USDRate(D("4.83"))
    ton = TONAmount.from_ton(D("120"))
    usd = ton.to_usd(rate)
    assert usd.usd == D("579.60")
    back = usd.to_ton(rate)
    assert back == ton
    assert usd.formatted == "$579.60"


def test_usd_rate_validation() -> None:
    with pytest.raises(MoneyError, match="положительным"):
        USDRate(D("0"))
    with pytest.raises(MoneyError, match="положительным"):
        USDRate(D("-1.2"))
    with pytest.raises(MoneyError, match="float запрещён"):
        USDRate(4.83)  # type: ignore[arg-type]


def test_usd_arithmetic_and_format() -> None:
    a = USDAmount.from_usd(D("10.005"))
    b = USDAmount.from_usd(D("0.004"))
    assert (a + b).formatted == "$10.01"  # ROUND_HALF_UP до центов
    assert (a - b).formatted == "$10.00"
    assert a.add(b) == a + b
    assert USDAmount.zero().formatted == "$0.00"


def test_negative_ton_allowed_but_guardable() -> None:
    neg = TONAmount.from_ton(D("-5"))
    assert neg.is_negative
    assert not neg.is_zero
    with pytest.raises(MoneyError, match="отрицательной"):
        neg.require_non_negative()
    assert TONAmount.zero().is_zero


def test_to_nano_int() -> None:
    assert TONAmount.from_ton(D("0.5")).to_nano_int() == 500_000_000


def test_format_ton_variants() -> None:
    assert format_ton(0) == "0"
    assert format_ton(NANO_PER_TON) == "1"
    assert format_ton(120 * NANO_PER_TON) == "120"
    assert format_ton(123_456_789) == "0.123457"
    assert format_ton(999_999) == "0.001"
    with pytest.raises(ValueError, match="отрицательным"):
        format_ton(-1)


def test_format_usd() -> None:
    assert format_usd(D("580.1")) == "$580.10"
    assert format_usd(D("1234.5")) == "$1234.50"
