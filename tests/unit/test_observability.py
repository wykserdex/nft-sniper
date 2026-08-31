"""Observability: метрики пайплайна и алерты деградации."""

from __future__ import annotations

from decimal import Decimal

import pytest

from nftsniper.observability import metrics
from nftsniper.observability.degradation import (
    DegradationAlert,
    DegradationThresholds,
    HealthSnapshot,
    check_degradation,
    emit_degradation_alerts,
)


def test_metrics_render_includes_pipeline_catalog() -> None:
    body = metrics.render_metrics()
    for name in (
        b"nft_sniper_pipeline_stage_seconds",
        b"nft_sniper_queue_size",
        b"nft_sniper_rate_limit_hits_total",
        b"nft_sniper_source_errors_total",
        b"nft_sniper_degradation_alerts_total",
    ):
        assert name in body


def test_metric_helpers_emit_labels() -> None:
    metrics.observe_stage("valuation", 0.05)
    metrics.set_queue_size("pending_alerts", 7)
    metrics.hit_rate_limit("dedup")
    metrics.record_source_error("tonapi", "http")
    body = metrics.render_metrics()
    assert b'stage="valuation"' in body
    assert b'queue="pending_alerts"' in body
    assert b'kind="dedup"' in body
    assert b'source="tonapi"' in body


def test_degradation_healthy_snapshot() -> None:
    assert check_degradation(HealthSnapshot()) == ()


def test_degradation_detects_all_rules() -> None:
    snapshot = HealthSnapshot(
        pending_listings=60_000,
        pending_alerts=25_000,
        source_errors_last_minute=150,
        rate_limit_hits_last_minute=3_000,
        valuation_p95_seconds=Decimal("6"),
        notify_p95_seconds=Decimal("4"),
    )
    alerts = check_degradation(snapshot)
    assert len(alerts) == 6
    assert all(alert.severity == "critical" for alert in alerts)


def test_degradation_warning_then_critical() -> None:
    warn = check_degradation(HealthSnapshot(pending_listings=15_000))
    assert len(warn) == 1
    assert warn[0].severity == "warning"
    assert warn[0].rule == "queue.pending_listings"

    crit = check_degradation(HealthSnapshot(pending_listings=60_000))
    assert crit[0].severity == "critical"


def test_degradation_custom_thresholds() -> None:
    thresholds = DegradationThresholds(pending_listings_warn=1, pending_listings_crit=100)
    alerts = check_degradation(HealthSnapshot(pending_listings=50), thresholds)
    assert len(alerts) == 1
    assert alerts[0].severity == "warning"
    assert alerts[0].threshold == Decimal("1")


def test_degradation_alert_validation() -> None:
    with pytest.raises(ValueError, match="severity"):
        DegradationAlert(
            rule="x",
            severity="fatal",
            field="f",
            threshold=Decimal("1"),
            value=Decimal("2"),
            message="m",
        )


def test_emit_degradation_alerts_records_counter() -> None:
    alert = DegradationAlert(
        rule="source_errors",
        severity="warning",
        field="source_errors_last_minute",
        threshold=Decimal("20"),
        value=Decimal("30"),
        message="рост ошибок",
    )
    emit_degradation_alerts([alert])
    assert b'rule="source_errors"' in metrics.render_metrics()
