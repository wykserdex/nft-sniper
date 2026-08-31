"""Базовые типы домена: Entity, ValueObject, DomainEvent.

Соглашения (из ТЗ):
- домен — чистый Python: ни infrastructure, ни entrypoints, ни внешние
  библиотеки (проверяется статически: tests/unit/test_domain_purity.py);
- все объекты иммутабельны (frozen dataclass): изменение = новый объект;
- Entity имеет поле ``id: str``; ValueObject — равенство по значению.
"""

from dataclasses import dataclass
from datetime import datetime


class Entity:
    """Сущность с идентичностью (поле ``id: str`` в конкретном классе)."""


class ValueObject:
    """Объект значения: тождествен по своим полям, иммутабилен."""


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Доменное событие: факт, который уже произошёл.

    Конкретные события объявляются в доменах контекстов
    (ListingDiscovered, ListingScored, AlertSent, ...).
    """

    occurred_at: datetime

    @property
    def name(self) -> str:
        return type(self).__name__
