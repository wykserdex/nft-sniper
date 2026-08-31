"""UserSettings: валидация ввода, мост в AlertPolicy, мьют/пауза."""

from decimal import Decimal

import pytest

from nftsniper.entrypoints.bot.domain import (
    SettingsValidationError,
    UserSettings,
    default_settings,
)
from nftsniper.shared.money import TONAmount

D = Decimal


def test_default_settings_language() -> None:
    assert default_settings("u1", None).language == "ru"
    assert default_settings("u1", "ru").language == "ru"
    assert default_settings("u1", "en").language == "en"
    assert default_settings("u1", "de").language == "ru"  # неизвестный → ru


def test_defaults_match_tz() -> None:
    settings = default_settings("u1", "ru")
    assert settings.min_discount == D("0.25")
    assert settings.min_confidence == D("0.5")
    assert settings.max_alerts_per_hour == 20


def test_update_min_discount_percent_and_fraction() -> None:
    settings = default_settings("u1", "ru")
    assert settings.with_update("min_discount", "25").min_discount == D("0.25")
    assert settings.with_update("min_discount", "25%").min_discount == D("0.25")
    assert settings.with_update("min_discount", "0.3").min_discount == D("0.3")


def test_update_rejects_bad_values() -> None:
    settings = default_settings("u1", "ru")
    for field, raw in (
        ("min_discount", "0"),  # строго > 0
        ("min_discount", "200"),  # > 100%
        ("min_discount", "abc"),
        ("min_confidence", "1.5"),
        ("min_confidence", "-0.1"),
        ("price_min", "-5"),
        ("max_risk", "2"),
    ):
        with pytest.raises(SettingsValidationError):
            settings.with_update(field, raw)


def test_update_price_range() -> None:
    settings = default_settings("u1", "ru")
    updated = settings.with_update("price_min", "10").with_update("price_max", "500")
    assert updated.price_min == TONAmount.from_ton(10)
    assert updated.price_max == TONAmount.from_ton(500)


def test_price_min_cannot_exceed_max() -> None:
    settings = default_settings("u1", "ru")
    low = settings.with_update("price_max", "10")
    with pytest.raises(SettingsValidationError, match="price_min"):
        low.with_update("price_min", "20")


def test_toggle_language() -> None:
    settings = default_settings("u1", "ru")
    assert settings.toggle_language().language == "en"
    assert settings.toggle_language().toggle_language().language == "ru"


def test_mute_collection_idempotent() -> None:
    settings = default_settings("u1", "ru")
    muted = settings.mute_collection("EQColl")
    assert muted.is_muted("EQColl")
    again = muted.mute_collection("EQColl")
    assert again.muted_collections == ("EQColl",)  # без дублей


def test_alert_policy_bridge() -> None:
    settings = default_settings("u1", "ru")
    policy = settings.alert_policy()
    assert policy.min_discount == D("0.25")
    assert policy.min_confidence == D("0.5")
    assert policy.price_max == TONAmount.from_ton(10000)


def test_unknown_field_rejected() -> None:
    with pytest.raises(SettingsValidationError, match="неизвестное"):
        default_settings("u1", "ru").with_update("nope", "1")


def test_bad_language_rejected_at_construction() -> None:
    with pytest.raises(SettingsValidationError, match="язык"):
        UserSettings(user_id="u1", language="fr")  # type: ignore[arg-type]
