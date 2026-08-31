"""TEP-2 адреса: векторы из TON docs, чек-сумма, ссылки на оплату, format_ton."""

import pytest

from nftsniper.shared.money import format_ton
from nftsniper.shared.ton_address import TonAddress, TonAddressError, parse_address

# Реальный TEP-2 вектор (TON docs / coin.space)
RAW = "0:88eddd9243d8a58bc5b8d6fa6c22e68cc9598131072c07111c334d5413968bfa"
UQ = "UQCI7d2SQ9ili8W41vpsIuaMyVmBMQcsBxEcM01UE5aL-j5l"  # non-bounceable, с CRC16
UQ_NOSUM = "UQCI7d2SQ9ili8W41vpsIuaMyVmBMQcsBxEcM01UE5aL-g"  # non-bounceable, без суммы
EQ = "EQCI7d2SQ9ili8W41vpsIuaMyVmBMQcsBxEcM01UE5aL-mOg"  # bounceable, с CRC16


def test_user_friendly_matches_tep2_vectors() -> None:
    a = TonAddress.from_raw(RAW)
    assert a.user_friendly(bounceable=False) == UQ
    assert a.user_friendly(bounceable=True) == EQ
    # без чек-суммы — 46 символов (34 байта core)
    assert a.user_friendly(bounceable=False, with_checksum=False) == UQ_NOSUM
    assert len(UQ) == 48
    assert len(UQ_NOSUM) == 46


def test_parse_all_forms_equal() -> None:
    raw = TonAddress.from_raw(RAW)
    assert parse_address(UQ) == raw
    assert parse_address(EQ) == raw
    assert parse_address(UQ_NOSUM) == raw
    assert parse_address(RAW) == raw


def test_raw_str_roundtrip() -> None:
    a = TonAddress.from_raw(RAW)
    assert a.raw_str == RAW
    assert a.workchain == 0
    assert len(a.raw_bytes) == 32


def test_workchain_minus_one_roundtrip() -> None:
    a = TonAddress(workchain=-1, raw_bytes=b"\x01" * 32)
    friendly = a.user_friendly(bounceable=False)
    assert parse_address(friendly).workchain == -1


def test_bad_checksum_rejected() -> None:
    bad = UQ[:-1] + ("a" if UQ[-1] != "a" else "b")
    with pytest.raises(TonAddressError, match="чек-сумма"):
        parse_address(bad)


def test_bad_length_rejected() -> None:
    with pytest.raises(TonAddressError, match="46 или 48"):
        parse_address("UQ-short")


def test_bad_base64_rejected() -> None:
    with pytest.raises(TonAddressError):
        parse_address("UQ" + "!" * 46)


def test_invalid_raw_rejected() -> None:
    with pytest.raises(TonAddressError):
        TonAddress.from_raw("5:ab")
    with pytest.raises(TonAddressError):
        TonAddress.from_raw("0:xyz")
    with pytest.raises(TonAddressError):
        TonAddress.from_raw("0:abcd")  # не 32 байта


def test_short() -> None:
    a = TonAddress.from_raw(RAW)
    s = a.short
    assert s.startswith("UQCI7d")
    assert s.endswith("-j5l")
    assert "…" in s


def test_payment_url_exact_format() -> None:
    a = TonAddress.from_raw(RAW)
    url = a.payment_url(123_456_789, "OTC-ABC123")
    assert url == f"ton://transfer/{UQ}?amount=123456789&text=OTC-ABC123"


def test_payment_url_without_optional_parts() -> None:
    a = TonAddress.from_raw(RAW)
    assert a.payment_url(0, "") == f"ton://transfer/{UQ}"


def test_comment_is_url_quoted() -> None:
    a = TonAddress.from_raw(RAW)
    url = a.payment_url(10, "a b&c")
    assert "text=a%20b%26c" in url


def test_tonkeeper_and_universal_links() -> None:
    a = TonAddress.from_raw(RAW)
    assert a.tonkeeper_url(5, "x").startswith(f"tonkeeper://transfer/{UQ}?")
    assert a.universal_link(5, "x").startswith(f"https://app.tonkeeper.com/transfer/{UQ}?")


def test_format_ton() -> None:
    assert format_ton(120_000_000_000) == "120"
    assert format_ton(0) == "0"
    assert format_ton(123_456_789) == "0.123457"
    assert format_ton(999_999) == "0.001"  # округление до 6 знаков
    with pytest.raises(ValueError, match="отрицательным"):
        format_ton(-1)
