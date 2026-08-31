"""Маркетплейсы (источники листингов)."""

from enum import StrEnum


class Marketplace(StrEnum):
    GETGEMS = "getgems"
    FRAGMENT = "fragment"
    TONAPI = "tonapi"
    TONX = "tonx"
    OTHER = "other"
