"""VerifySales: сверка выборки продаж с on-chain.

Критерий готовности: «on-chain цена совпадает с API-ценой на выборке
из 100 сделок, расхождения помечены» (ТЗ §7). Use case берёт детерминированную
выборку до ``sample_size`` (по умолчанию 100) продаж, сверяет их через
``ChainPort.verify_sales`` и возвращает расхождения отдельным списком —
именно по ним потребитель «помечает» записи (лог/флаг/метрика).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from nftsniper.contexts.sources.domain.chain import SaleVerification
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.sources.ports import ChainPort

DEFAULT_SAMPLE_SIZE = 100


@dataclass(frozen=True, slots=True)
class VerifySalesResult:
    """Итог сверки: все верификации + расхождения (``matches=False``)."""

    verified: tuple[SaleVerification, ...]
    mismatches: tuple[SaleVerification, ...]

    @property
    def checked_count(self) -> int:
        return len(self.verified)

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)


def deterministic_sample(sales: Sequence[SaleEvent], size: int) -> list[SaleEvent]:
    """Детерминированная выборка ``size`` продаж (равномерно по сортировке id).

    Чисто целочисленная арифметика (без float): индексы
    ``i * (n − 1) // (size − 1)`` покрывают диапазон от первого до последнего
    элемента и дают ровно ``size`` уникальных индексов при ``1 < size <= n``.
    """
    if size <= 0:
        return []
    ordered = sorted(sales, key=lambda sale: sale.id)
    total = len(ordered)
    if total <= size:
        return ordered
    if size == 1:
        return [ordered[0]]
    indices = [index * (total - 1) // (size - 1) for index in range(size)]
    return [ordered[i] for i in indices]


class VerifySales:
    """Сверка выборки до ``sample_size`` продаж с on-chain (ТЗ §7)."""

    def __init__(self, chain: ChainPort, *, sample_size: int = DEFAULT_SAMPLE_SIZE) -> None:
        self._chain = chain
        self._sample_size = sample_size

    async def run(self, sales: Sequence[SaleEvent]) -> VerifySalesResult:
        sample = deterministic_sample(sales, self._sample_size)
        verifications = await self._chain.verify_sales(sample)
        mismatches = tuple(
            verification for verification in verifications if not verification.matches
        )
        return VerifySalesResult(verified=tuple(verifications), mismatches=mismatches)
