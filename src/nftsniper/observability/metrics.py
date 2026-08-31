"""Prometheus-метрики.

Базовый набор каркаса + полный каталог (ТЗ §12):
- счётчики ingestion/алертов;
- latency пайплайна по этапам (poller/valuate/risk/match/notify);
- размеры очередей (pending);
- срабатывания rate limit и фильтров алертов;
- ошибки источников (getgems/tonapi/fragment);
- алерты деградации.

Метрики с метками заполняются через helper'ы (``observe_stage``, ...).
Здесь измеряются физические величины (секунды, счётчики), поэтому float
допустим — ``observability`` в whitelist'е no-float (ТЗ: float запрещён
в деньгах и бизнес-логике, не в метриках).
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

# ── каталог  ────────────────────────────────────────────────────

pipeline_stage_seconds = Histogram(
    "nft_sniper_pipeline_stage_seconds",
    "Задержка этапа пайплайна, сек",
    labelnames=("stage",),
    registry=registry,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

queue_size = Gauge(
    "nft_sniper_queue_size",
    "Размер очередей пайплайна (pending)",
    labelnames=("queue",),
    registry=registry,
)

rate_limit_hits_total = Counter(
    "nft_sniper_rate_limit_hits_total",
    "Срабатывания rate limit и фильтров алертов",
    labelnames=("kind",),
    registry=registry,
)

source_errors_total = Counter(
    "nft_sniper_source_errors_total",
    "Ошибки источников данных",
    labelnames=("source", "kind"),
    registry=registry,
)

degradation_alerts_total = Counter(
    "nft_sniper_degradation_alerts_total",
    "Срабатывания алертов деградации",
    labelnames=("rule",),
    registry=registry,
)

uptime_seconds = Gauge(
    "nft_sniper_uptime_seconds",
    "Аптайм процесса, сек",
    registry=registry,
)

CONTENT_TYPE = CONTENT_TYPE_LATEST

# Этапы пайплайна (ТЗ §6): poller → valuation → risk → matching → notify.
PIPELINE_STAGES = ("poller", "valuate", "risk", "match", "notify")


def observe_stage(stage: str, seconds: float) -> None:
    """Записать задержку этапа пайплайна (сек)."""
    pipeline_stage_seconds.labels(stage=stage).observe(seconds)


def set_queue_size(queue: str, size: int) -> None:
    """Текущий размер очереди (``queue``: pending_listings/scores/alerts)."""
    queue_size.labels(queue=queue).set(size)


def hit_rate_limit(kind: str) -> None:
    """Срабатывание лимита/фильтра (``kind``: dedup/rate_limit/quiet)."""
    rate_limit_hits_total.labels(kind=kind).inc()


def record_source_error(source: str, kind: str) -> None:
    """Ошибка источника (``source``: getgems/tonapi/fragment; kind: http/parse)."""
    source_errors_total.labels(source=source, kind=kind).inc()


def record_degradation_alert(rule: str) -> None:
    """Срабатывание алерта деградации по правилу ``rule``."""
    degradation_alerts_total.labels(rule=rule).inc()


def render_metrics() -> bytes:
    """Снимок метрик в Prometheus text format."""
    return generate_latest(registry)
