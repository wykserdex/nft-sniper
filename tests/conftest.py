"""Общие фикстуры: изолированные настройки без .env и env-переменных окружения."""

import pytest

from nftsniper.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="dev",
        log_level="INFO",
        log_json=True,
        http_port=8123,
    )
