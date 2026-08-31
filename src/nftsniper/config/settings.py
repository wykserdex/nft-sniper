"""Настройки приложения.

Все значения приходят из переменных окружения с префиксом ``NFT_``
или файла ``.env``. Секреты — только через ``SecretStr``, чтобы не
попадать в логи и репрезентации.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "staging", "prod"]
Language = Literal["ru", "en"]

_ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class Settings(BaseSettings):
    """Снапшот конфигурации одного запуска. Создаётся один раз (см. get_settings)."""

    model_config = SettingsConfigDict(
        env_prefix="NFT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── ядро ────────────────────────────────────────────────────────────
    app_env: AppEnv = "dev"
    log_level: str = "INFO"
    log_json: bool = False

    # ── HTTP-сервер (health endpoint) ───────────────────────────────────
    http_host: str = "0.0.0.0"
    http_port: int = Field(default=8080, ge=1, le=65535)

    # ── инфраструктура ──────────────────────────────────────────────────
    postgres_dsn: str = "postgresql+asyncpg://nft_sniper:nft_sniper@localhost:5432/nft_sniper"
    redis_url: str = "redis://localhost:6379/0"

    # ── telegram ────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr | None = None
    default_language: Language = "ru"

    # ── внешние источники (заполняются на фазе) ─────────────
    getgems_api_key: SecretStr | None = None
    tonapi_key: SecretStr | None = None

    # ── дефолты алертов (переопределяются настройками пользователя) ─────
    default_min_discount: Decimal = Field(default=Decimal("0.25"), gt=0, lt=1)
    default_min_confidence: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    default_max_alerts_per_hour: int = Field(default=20, gt=0)
    alert_latency_target_ms: int = Field(default=3000, gt=0)

    # ── mini app (правка к ТЗ, §11) ─────────────────────────────────────
    # Публичный URL мини-аппа для WebAppInfo-кнопок бота
    webapp_url: str = "http://localhost:8080"
    # Срок оплаты OTC-сделки
    otc_ttl_minutes: int = Field(default=30, gt=0, le=1440)

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _ALLOWED_LOG_LEVELS:
            msg = (
                f"log_level должен быть одним из {sorted(_ALLOWED_LOG_LEVELS)}, получено {value!r}"
            )
            raise ValueError(msg)
        return normalized

    @field_validator("postgres_dsn")
    @classmethod
    def _validate_postgres_dsn(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            msg = "postgres_dsn должен использовать драйвер postgresql+asyncpg:// (async)"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    """Единственный экземпляр настроек на процесс."""
    return Settings()
