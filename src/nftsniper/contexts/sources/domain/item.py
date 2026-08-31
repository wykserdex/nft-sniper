"""Предмет NFT: идентификатор, трейты, редкость."""

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.shared.domain.base import Entity, ValueObject


@dataclass(frozen=True, slots=True)
class Trait(ValueObject):
    """Один признак предмета. ``rarity`` — доля предметов коллекции с
    таким значением (Decimal 0..1), если известна."""

    name: str
    value: str
    rarity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TraitSet(ValueObject):
    """Множество признаков предмета."""

    traits: tuple[Trait, ...]

    def get(self, name: str) -> Trait | None:
        for trait in self.traits:
            if trait.name == name:
                return trait
        return None

    def __len__(self) -> int:
        return len(self.traits)

    def __iter__(self) -> Iterator[Trait]:
        return iter(self.traits)


@dataclass(frozen=True, slots=True)
class Item(Entity):
    """Предмет коллекции. ``id`` — on-chain-адрес NFT (источник истины).

    ``rarity_rank`` — перцентиль редкости в коллекции (0..1, меньше = реже);
    ``rarity_score`` — нормированный скор (0..1), вычисляемый.
    ``media_url`` — ссылка на медиа (изображение/контент), заполняется
    адаптером источника; используется risk-проверкой доступности медиа
    (ТЗ §4). None, если неизвестна.
    """

    id: str
    collection_id: str
    index: int
    name: str
    traits: TraitSet = TraitSet(traits=())
    rarity_rank: Decimal | None = None
    rarity_score: Decimal | None = None
    media_url: str | None = None
