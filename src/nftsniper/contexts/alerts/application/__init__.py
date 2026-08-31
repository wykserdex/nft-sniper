"""Use cases alerts: MatchListing, AlertEngine, RecordDecision.

Матчинг — чистая функция (matcher.py); движок (engine.py) делает
дедупликацию, rate limit, quiet hours, приоритизацию и доставку через
порты; RecordDecision — каноническая запись решения (использует).
"""

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

__all__ = [
    "AlertEngine",
    "DeliveryReport",
    "MatchOutcome",
    "PrioritizedQueue",
    "RecordDecision",
    "RecordDecisionResult",
    "Renderer",
    "candidate_priority",
    "match_listing",
]
