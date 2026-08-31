"""Гейт изменения модели: сравнительный бэктест перед деплоем.

Критерий ТЗ §7: «любое изменение valuation прогоняется через бэктест и даёт
сравнимый отчёт». ``compare_models`` гоняет baseline и candidate по одним
историческим данным (walk-forward без look-ahead, из ``run_backtest``) и
возвращает ``ModelComparisonReport``: медианные ошибки обеих моделей, дельта
и вердикт ``promote`` — кандидат проходит собственный порог и не хуже
baseline более чем на ``tolerance`` (проц. пунктов MAPE).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.application.backtest import (
    DEFAULT_ERROR_THRESHOLD,
    BacktestReport,
    run_backtest,
)
from nftsniper.contexts.valuation.ports import PriceModelPort

DEFAULT_REGRESSION_TOLERANCE = Decimal("0.05")  # +5 п.п. MAPE допустимой регрессии


@dataclass(frozen=True, slots=True)
class ModelComparisonReport:
    """Сравнимый отчёт двух прогонов бэктеста (baseline vs candidate)."""

    baseline: BacktestReport
    candidate: BacktestReport
    tolerance: Decimal

    @property
    def delta(self) -> Decimal:
        """Насколько медианная ошибка кандидата выше baseline (может быть < 0)."""
        return self.candidate.median_error - self.baseline.median_error

    @property
    def promote(self) -> bool:
        """Можно ли деплоить кандидата.

        Кандидат должен сам пройти порог ошибки и не регрессировать
        относительно baseline более чем на ``tolerance``.
        """
        return self.candidate.passed and self.delta <= self.tolerance

    @property
    def summary(self) -> str:
        verdict = "PROMOTE" if self.promote else "REJECT"
        return (
            f"baseline median_error={self.baseline.median_error}, "
            f"candidate median_error={self.candidate.median_error}, "
            f"delta={self.delta}, verdict={verdict}"
        )


async def compare_models(
    *,
    baseline: PriceModelPort,
    candidate: PriceModelPort,
    sales: Sequence[SaleEvent],
    active_listings: Sequence[Listing],
    item_by_id: Mapping[str, Item],
    threshold: Decimal = DEFAULT_ERROR_THRESHOLD,
    tolerance: Decimal = DEFAULT_REGRESSION_TOLERANCE,
) -> ModelComparisonReport:
    """Прогнать baseline и candidate по одним данным и сравнить (ТЗ §7, §12)."""
    baseline_report = await run_backtest(
        model=baseline,
        sales=sales,
        active_listings=active_listings,
        item_by_id=item_by_id,
        threshold=threshold,
    )
    candidate_report = await run_backtest(
        model=candidate,
        sales=sales,
        active_listings=active_listings,
        item_by_id=item_by_id,
        threshold=threshold,
    )
    return ModelComparisonReport(
        baseline=baseline_report,
        candidate=candidate_report,
        tolerance=tolerance,
    )
