"""RecordDecision: запись решения + доменное событие."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nftsniper.contexts.alerts.application.decisions import RecordDecision
from nftsniper.contexts.alerts.domain.events import DecisionRecorded
from tests.fakes import InMemoryDecisionRepository

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


async def test_record_decision_saves_and_emits_event() -> None:
    repo = InMemoryDecisionRepository()
    use_case = RecordDecision(repo, clock=lambda: NOW, id_factory=lambda: "dec-1")
    result = await use_case.run(alert_id="al-1", user_id="u1", action="taken", latency_ms=850)
    assert result.decision.id == "dec-1"
    assert result.decision.alert_id == "al-1"
    assert result.decision.created_at == NOW
    assert isinstance(result.event, DecisionRecorded)
    assert result.event.alert_id == "al-1"
    assert result.event.action == "taken"
    assert result.event.latency_ms == 850

    saved = await repo.list_by_alert("al-1")
    assert len(saved) == 1
    assert saved[0].user_id == "u1"


async def test_record_decision_invalid_action_raises() -> None:
    repo = InMemoryDecisionRepository()
    use_case = RecordDecision(repo, clock=lambda: NOW)
    with pytest.raises(ValueError, match="действие"):
        await use_case.run(alert_id="al-1", user_id="u1", action="yolo", latency_ms=1)
