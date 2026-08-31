"""Домен risk: RiskFlag, RiskScore."""

from decimal import Decimal

import pytest

from nftsniper.contexts.risk.domain import RiskFlag, RiskScore, RiskSeverity


def flag(code: str, severity: str, message: str = "m") -> RiskFlag:
    return RiskFlag(code=code, severity=severity, message=message)


def test_severity_values_ordering() -> None:
    assert flag("X", RiskSeverity.LOW).value < flag("X", RiskSeverity.MEDIUM).value
    assert flag("X", RiskSeverity.MEDIUM).value < flag("X", RiskSeverity.HIGH).value


def test_bad_severity_rejected() -> None:
    with pytest.raises(ValueError, match="severity"):
        flag("X", "EPIC")


def test_risk_score_clean() -> None:
    score = RiskScore.clean()
    assert score.value == 0
    assert score.flags == ()
    assert score.worst_severity is None
    assert score.passes(Decimal("0"))


def test_with_flag_raises_value_to_severity_floor() -> None:
    score = RiskScore.clean().with_flag(flag("FRESH_SELLER", RiskSeverity.HIGH, "свежий кошелёк"))
    assert score.value == Decimal("0.9")
    assert score.worst_severity == RiskSeverity.HIGH
    # low-флаг не снижает score
    score2 = score.with_flag(flag("UNKNOWN_SELLER", RiskSeverity.LOW))
    assert score2.value == Decimal("0.9")
    assert len(score2.flags) == 2


def test_risk_score_bounded() -> None:
    with pytest.raises(ValueError, match="risk score"):
        RiskScore(value=Decimal("1.2"))
    with pytest.raises(ValueError, match="risk score"):
        RiskScore(value=Decimal("-0.1"))


def test_passes_max_score() -> None:
    score = RiskScore(value=Decimal("0.5"))
    assert score.passes(Decimal("0.5"))
    assert not score.passes(Decimal("0.4"))
