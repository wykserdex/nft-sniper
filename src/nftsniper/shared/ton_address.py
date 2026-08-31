"""Адреса TON (TEP-2): валидация, конвертация форматов, ссылки на оплату.

Форматы:
- raw: ``0:hex64`` / ``-1:hex64`` (workchain + 32 байта);
- user-friendly: base64url без padding — 46 символов (без чек-суммы)
  или 48 (CRC16-XMODEM в 2 байтах). ``EQ…`` — bounceable, ``UQ…`` — non-bounceable.

Ссылки на оплату (формат TON Foundation / TON Keeper):
- универсальная (и QR, и deep-link): ``ton://transfer/{ADDR}?amount={nano}&text={comment}``
- TON Keeper: ``tonkeeper://transfer/...`` и universal-link ``https://app.tonkeeper.com/transfer/...``

Здесь только int nanoTON и стринги — float запрещён гейтом no_float.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

_BOUNCEABLE_TAG = 0x11  # EQ…
_NON_BOUNCEABLE_TAG = 0x51  # UQ…
_CORE_LEN = 34  # tag(1) + workchain(1) + address(32)
_ADDR_LEN = 32
_FRI_LEN_NO_CHECKSUM = 46  # 34 байта → 46 символов base64url
_FRI_LEN_CHECKSUM = 48  # 36 байт (34 + CRC16) → 48 символов
_VALID_WORKCHAINS = (-1, 0, 1)
_MAX_COMMENT_LEN = 64
_WC_SIGN_BIT = 0x80
_WC_BYTE_OFFSET = 0x100


class TonAddressError(ValueError):
    """Некорректный TON-адрес."""


def crc16_xmodem(data: bytes) -> int:
    """CRC16-XMODEM (полином 0x1021, init 0x0000) — чек-сумма TEP-2."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    try:
        padded = text + "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        msg = f"не base64url: {exc}"
        raise TonAddressError(msg) from exc


@dataclass(frozen=True, slots=True)
class TonAddress:
    """Канонический адрес: workchain + 32 байта. Хэш-равенство по паре."""

    workchain: int
    raw_bytes: bytes

    def __post_init__(self) -> None:
        if self.workchain not in _VALID_WORKCHAINS:
            msg = f"workchain должен быть -1/0/1, получено {self.workchain}"
            raise TonAddressError(msg)
        if len(self.raw_bytes) != _ADDR_LEN:
            msg = f"адрес должен быть ровно {_ADDR_LEN} байт"
            raise TonAddressError(msg)

    # ── парсинг ─────────────────────────────────────────────────────────

    @classmethod
    def from_raw(cls, raw: str) -> TonAddress:
        """``0:88ed…`` / ``-1:…`` (hex, 64 символа после двоеточия)."""
        try:
            wc_text, hex_text = raw.strip().split(":", 1)
            workchain = int(wc_text)
            addr = bytes.fromhex(hex_text)
        except (ValueError, AttributeError) as exc:
            msg = f"ожидался формат raw '0:hex64', получено {raw!r}"
            raise TonAddressError(msg) from exc
        return cls(workchain=workchain, raw_bytes=addr)

    @classmethod
    def from_user_friendly(cls, text: str) -> TonAddress:
        """``EQ…``/``UQ…`` — 46 символов (без суммы) или 48 (с CRC16)."""
        s = text.strip()
        if len(s) == _FRI_LEN_NO_CHECKSUM:
            core = _b64url_decode(s)
            if len(core) != _CORE_LEN:
                msg = "плохая длина core TEP-2"
                raise TonAddressError(msg)
        elif len(s) == _FRI_LEN_CHECKSUM:
            full = _b64url_decode(s)
            if len(full) != _CORE_LEN + 2:
                msg = "плохая длина TEP-2 с чек-суммой"
                raise TonAddressError(msg)
            expected = crc16_xmodem(full[:_CORE_LEN])
            if full[_CORE_LEN:] != expected.to_bytes(2, "big"):
                msg = f"чек-сумма TEP-2 не сходится: {s}"
                raise TonAddressError(msg)
            core = full[:_CORE_LEN]
        else:
            msg = (
                f"user-friendly адрес должен быть 46 или 48 символами, получено {len(s)} "
                f"(EQ…/UQ…, как показывает TON Keeper)"
            )
            raise TonAddressError(msg)

        tag, wc_byte = core[0], core[1]
        if tag in (_BOUNCEABLE_TAG, _NON_BOUNCEABLE_TAG):
            workchain = wc_byte if wc_byte < _WC_SIGN_BIT else wc_byte - _WC_BYTE_OFFSET
        else:
            msg = f"неизвестный tag TEP-2: 0x{tag:02x}"
            raise TonAddressError(msg)
        return cls(workchain=workchain, raw_bytes=core[2:])

    # ── форматы ─────────────────────────────────────────────────────────

    @property
    def raw_str(self) -> str:
        return f"{self.workchain}:{self.raw_bytes.hex()}"

    def user_friendly(self, *, bounceable: bool = False, with_checksum: bool = True) -> str:
        """Строка для человека. По умолчанию non-bounceable с чек-суммой (UQ…)."""
        tag = _BOUNCEABLE_TAG if bounceable else _NON_BOUNCEABLE_TAG
        core = bytes([tag, self.workchain & 0xFF]) + self.raw_bytes
        if with_checksum:
            core += crc16_xmodem(core).to_bytes(2, "big")
        return _b64url_encode(core)

    @property
    def short(self) -> str:
        """Сокращённый вид для UI: ``EQAB…JUF``."""
        full = self.user_friendly()
        return f"{full[:6]}…{full[-4:]}"

    # ── ссылки на оплату ────────────────────────────────────────────────

    def _transfer_base(self, address_text: str, amount_nano: int, comment: str) -> str:
        if amount_nano < 0:
            msg = "amount_nano не может быть отрицательным"
            raise TonAddressError(msg)
        url = f"ton://transfer/{address_text}"
        query: list[str] = []
        if amount_nano > 0:
            query.append(f"amount={amount_nano}")
        if comment:
            if len(comment) > _MAX_COMMENT_LEN:
                comment = comment[:_MAX_COMMENT_LEN]
            query.append(f"text={quote(comment, safe='')}")
        if query:
            url += "?" + "&".join(query)
        return url

    def payment_url(self, amount_nano: int, comment: str = "") -> str:
        """Универсальная ссылка оплаты = содержимое TON QR (Tonkeeper/Tonhub/Wallet)."""
        return self._transfer_base(self.user_friendly(bounceable=False), amount_nano, comment)

    def tonkeeper_url(self, amount_nano: int, comment: str = "") -> str:
        """Deep-link, открывающий TON Keeper с заполненным переводом."""
        url = self.payment_url(amount_nano, comment)
        return url.replace("ton://", "tonkeeper://", 1)

    def universal_link(self, amount_nano: int, comment: str = "") -> str:
        """Universal link TON Keeper (работает и в системном share-sheet)."""
        url = self.payment_url(amount_nano, comment)
        return url.replace("ton://transfer/", "https://app.tonkeeper.com/transfer/", 1)


def parse_address(text: str) -> TonAddress:
    """Автоопределение формата: raw (``0:hex``) или user-friendly (``EQ…``/``UQ…``)."""
    s = text.strip()
    if ":" in s and s.split(":", 1)[0] in ("-1", "0", "1"):
        return TonAddress.from_raw(s)
    return TonAddress.from_user_friendly(s)
