"""Источник времени для use cases (подменяется в тестах)."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Текущее время в UTC (ISO 8601, aware)."""
    return datetime.now(UTC)
