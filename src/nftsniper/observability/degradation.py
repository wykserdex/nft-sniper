"""Алерты деградации: проверка здоровья пайплайна.

``check_degradation`` — чистая функция: снимок здоровья → кортеж
``DegradationAlert`` по порогам. Проверяются (ТЗ §12): глубина очередей,
ошибки источников, срабатывания rate limit, latency p95 этапов оценка/
доставка. Пороги — ``DegradationThresholds`` (переопределяемы). Значения —
Decimal/счётчики: детерминированно и сравнимо в тестах.

``emit_degradation_alerts`` связывает алерты с Prometheus-счётчиком
(``nft_sniper_degradation_alerts_total``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.observability.metrics import record_degradation_alert

SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Снимок здоровья пайплайна для проверки деградации."""

    pending_listings: int = 0
    pending_scores: int = 0
    pending_alerts: int = 0
    source_errors_last_minute: int = 0
    rate_limit_hits_last_minute: int = 0
    valuation_p95_seconds: Decimal = Decimal("0")
    notify_p95_seconds: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class DegradationThresholds:
    """Пороги деградации (по умолчанию — согласованные для MVP)."""

    pending_listings_warn: int = 10_000
    pending_listings_crit: int = 50_000
    pending_alerts_warn: int = 5_000
    pending_alerts_crit: int = 20_000
    source_errors_warn: int = 20  # ошибок/мин
    source_errors_crit: int = 100
    rate_limit_warn: int = 500  # срабатываний/мин
    rate_limit_crit: int = 2_000
    valuation_p95_warn: Decimal = Decimal("2.5")  # сек (цель ТЗ §6: < 3с)
    valuation_p95_crit: Decimal = Decimal("5.0")
    notify_p95_warn: Decimal = Decimal("1.0")
    notify_p95_crit: Decimal = Decimal("3.0")


@dataclass(frozen=True, slots=True)
class DegradationAlert:
    """Одно срабатывание: правило, тяжесть, читаемое сообщение."""

    rule: str
    severity: str  # warning | critical
    field: str
    threshold: Decimal
    value: Decimal
    message: str

    def __post_init__(self) -> None:
        if self.severity not in (SEVERITY_WARNING, SEVERITY_CRITICAL):
            msg = f"неизвестная severity: {self.severity}"
            raise ValueError(msg)


def _severity(value: Decimal, warn: Decimal, crit: Decimal) -> str | None:
    if value > crit:
        return SEVERITY_CRITICAL
    if value > warn:
        return SEVERITY_WARNING
    return None


def check_degradation(
    snapshot: HealthSnapshot,
    thresholds: DegradationThresholds | None = None,
) -> tuple[DegradationAlert, ...]:
    """Проверить снимок здоровья и вернуть алерты деградации (чистая функция)."""
    t = thresholds if thresholds is not None else DegradationThresholds()
    alerts: list[DegradationAlert] = []

    def consider(
        rule: str,
        field: str,
        value: int | Decimal,
        warn: int | Decimal,
        crit: int | Decimal,
        *,
        message: str,
    ) -> None:
        v = value if isinstance(value, Decimal) else Decimal(value)
        severity = _severity(v, Decimal(warn), Decimal(crit))
        if severity is None:
            return
        limit = Decimal(crit) if severity == SEVERITY_CRITICAL else Decimal(warn)
        alerts.append(
            DegradationAlert(
                rule=rule,
                severity=severity,
                field=field,
                threshold=limit,
                value=v,
                message=message,
            )
        )

    consider(
        "queue.pending_listings",
        "pending_listings",
        snapshot.pending_listings,
        t.pending_listings_warn,
        t.pending_listings_crit,
        message="очередь листингов переполнена — poller не справляется",
    )
    consider(
        "queue.pending_alerts",
        "pending_alerts",
        snapshot.pending_alerts,
        t.pending_alerts_warn,
        t.pending_alerts_crit,
        message="очередь алертов переполнена — notifier отстаёт",
    )
    consider(
        "source_errors",
        "source_errors_last_minute",
        snapshot.source_errors_last_minute,
        t.source_errors_warn,
        t.source_errors_crit,
        message="рост ошибок источников — возможно, деградация API",
    )
    consider(
        "rate_limit_hits",
        "rate_limit_hits_last_minute",
        snapshot.rate_limit_hits_last_minute,
        t.rate_limit_warn,
        t.rate_limit_crit,
        message="аномально много срабатываний rate limit",
    )
    consider(
        "latency.valuation_p95",
        "valuation_p95_seconds",
        snapshot.valuation_p95_seconds,
        t.valuation_p95_warn,
        t.valuation_p95_crit,
        message="оценка тормозит: p95 выше цели 3 сек",
    )
    consider(
        "latency.notify_p95",
        "notify_p95_seconds",
        snapshot.notify_p95_seconds,
        t.notify_p95_warn,
        t.notify_p95_crit,
        message="доставка алертов тормозит",
    )
    return tuple(alerts)


def emit_degradation_alerts(alerts: Sequence[DegradationAlert]) -> None:
    """Связать алерты деградации с Prometheus-счётчиком."""
    for alert in alerts:
        record_degradation_alert(alert.rule)
