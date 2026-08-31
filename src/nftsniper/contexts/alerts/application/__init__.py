"""Use cases alerts.

- MatchListing (matcher.py) — чистый матчинг листинга с подписчиком;
- AlertEngine (engine.py) — дедуп, rate limit, quiet hours, приоритизация,
  доставка через порты;
- RecordDecision (decisions.py) — запись решения + событие;
- TrackOutcome (outcome_tracking.py) — трекинг исходов 1h/24h/7d;
- AlertAnalytics (analytics.py) — precision/take rate/hit rate, контрфактуал
  «что было бы, если бы взяли всё», рекомендация порога min_discount.
"""

from nftsniper.contexts.alerts.application.analytics import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_TARGET_PRECISION,
    AlertAnalytics,
    CounterfactualReport,
    QualityReport,
    ThresholdRecommendation,
    compute_counterfactual,
    compute_quality,
    recommend_threshold,
)
from nftsniper.contexts.alerts.application.decisions import (
    RecordDecision,
    RecordDecisionResult,
)
from nftsniper.contexts.alerts.application.engine import (
    AlertEngine,
    DeliveryReport,
    PrioritizedQueue,
    Renderer,
)
from nftsniper.contexts.alerts.application.matcher import (
    MatchOutcome,
    candidate_priority,
    match_listing,
)
from nftsniper.contexts.alerts.application.outcome_tracking import TrackOutcome

__all__ = [
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_TARGET_PRECISION",
    "AlertAnalytics",
    "AlertEngine",
    "CounterfactualReport",
    "DeliveryReport",
    "MatchOutcome",
    "PrioritizedQueue",
    "QualityReport",
    "RecordDecision",
    "RecordDecisionResult",
    "Renderer",
    "ThresholdRecommendation",
    "TrackOutcome",
    "candidate_priority",
    "compute_counterfactual",
    "compute_quality",
    "match_listing",
    "recommend_threshold",
]
