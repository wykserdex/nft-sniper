"""Prometheus-метрики.

Базовый набор для каркаса; полный каталог (latency pipeline по этапам,
размер очередей, срабатывания rate limit, ошибки источников) —.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

registry = CollectorRegistry()

listings_ingested_total = Counter(
    "nft_sniper_listings_ingested_total",
    "Листинги, принятые из источников",
    registry=registry,
)

alerts_sent_total = Counter(
    "nft_sniper_alerts_sent_total",
    "Алерты, доставленные пользователям",
    registry=registry,
)

alerts_dropped_total = Counter(
    "nft_sniper_alerts_dropped_total",
    "Алерты, отброшенные фильтрами/лимитами",
    registry=registry,
)

valuation_seconds = Histogram(
    "nft_sniper_valuation_seconds",
    "Время оценки справедливой цены, сек",
    registry=registry,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

uptime_seconds = Gauge(
    "nft_sniper_uptime_seconds",
    "Аптайм процесса, сек",
    registry=registry,
)

CONTENT_TYPE = CONTENT_TYPE_LATEST


def render_metrics() -> bytes:
    """Снимок метрик в Prometheus text format."""
    return generate_latest(registry)
