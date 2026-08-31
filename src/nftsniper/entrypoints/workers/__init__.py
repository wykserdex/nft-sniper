"""Фоновые воркеры — строятся вместе с контекстами.

- poller     — опрос источников, 2–5 сек
- valuator   — ансамбль оценки + risk screening
- notifier   — матчинг с пользователями, rate limit, отправка
- calibrator — ночное переобучение весов

``ListingPipeline`` (pipeline.py) склеивает poller → valuator → notifier
в один проход; ``runner.py`` даёт цикл с метриками, трекер исходов (1h/24h/7d)
и калибратор; ``wiring.py`` собирает реальные адаптеры + Postgres/Redis.
"""

from nftsniper.entrypoints.workers.pipeline import (
    ListingPipeline,
    PipelineReport,
    getgems_item_url,
)
from nftsniper.entrypoints.workers.runner import (
    CalibrationRecommendation,
    OutcomeTracker,
    run_calibrator_once,
    run_pipeline_loop,
)
from nftsniper.entrypoints.workers.wiring import WorkerComponents, build_worker

__all__ = [
    "CalibrationRecommendation",
    "ListingPipeline",
    "OutcomeTracker",
    "PipelineReport",
    "WorkerComponents",
    "build_worker",
    "getgems_item_url",
    "run_calibrator_once",
    "run_pipeline_loop",
]
