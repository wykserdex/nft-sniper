"""Настройки: дефолты, env-оверрайды, валидация, секреты."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from nftsniper.config.settings import Settings


def test_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.app_env == "dev"
    assert s.http_port == 8080
    assert s.log_level == "INFO"
    assert s.default_min_discount == Decimal("0.25")
    assert s.default_min_confidence == Decimal("0.50")
    assert s.default_max_alerts_per_hour == 20
    assert s.alert_latency_target_ms == 3000
    assert s.postgres_dsn.startswith("postgresql+asyncpg://")
    assert s.telegram_bot_token is None


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_HTTP_PORT", "9999")
    monkeypatch.setenv("NFT_DEFAULT_MIN_DISCOUNT", "0.35")
    monkeypatch.setenv("NFT_LOG_LEVEL", "debug")
    monkeypatch.setenv("NFT_APP_ENV", "prod")

    s = Settings(_env_file=None)
    assert s.http_port == 9999
    assert s.default_min_discount == Decimal("0.35")
    assert s.log_level == "DEBUG"
    assert s.app_env == "prod"


def test_port_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_HTTP_PORT", "70000")
    with pytest.raises(ValidationError, match="http_port"):
        Settings(_env_file=None)


def test_discount_must_be_in_0_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_DEFAULT_MIN_DISCOUNT", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_dsn_must_use_asyncpg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_POSTGRES_DSN", "postgres://user:pass@localhost/db")
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None)


def test_unknown_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_LOG_LEVEL", "chill")
    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None)


def test_secret_token_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_TELEGRAM_BOT_TOKEN", "123456:SECRET-TOKEN")
    s = Settings(_env_file=None)
    assert s.telegram_bot_token is not None
    assert s.telegram_bot_token.get_secret_value() == "123456:SECRET-TOKEN"
    assert "SECRET-TOKEN" not in repr(s)


def test_unknown_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFT_SOMETHING_UNKNOWN", "x")
    s = Settings(_env_file=None)
    assert s.app_env == "dev"
