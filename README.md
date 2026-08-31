# NFT Sniper

Telegram-бот для поиска недооценённых NFT на TON.
**Бот не покупает.** Он находит, оценивает, объясняет и спрашивает. Решение всегда за человеком.

Полное ТЗ — в [docs/TZ.md](docs/TZ.md).

```
Новый листинг → Оценка справедливой цены → Расчёт дискаунта
  → Если дисконт > порога → Алерт в Telegram
  → Кнопки: Взять / Скип / Следить / Мьют коллекции
  → Решение записывается → используется для калибровки модели
```

## Стек

Python 3.12, aiogram 3, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis 7,
httpx, Pydantic v2 (только на границах), structlog, FastAPI (health),
pytest, ruff, mypy strict, alembic, prometheus-client.

## Быстрый старт

```bash
make install          # venv: pip install -e ".[dev]"
cp .env.example .env
make compose-up       # Postgres 16 + Redis 7
make migrate          # alembic upgrade head
make run              # nftsniper serve → http://localhost:8080
```

Проверка:

```bash
curl localhost:8080/healthz   # liveness
curl localhost:8080/readyz    # Postgres + Redis
curl localhost:8080/metrics   # Prometheus
nftsniper check               # CLI-верификация связности (exit 0/1)
```

Качественные проверки (то, что гоняет CI):

```bash
make lint       # ruff format --check, ruff check, mypy strict, no-float гейт
make test       # unit + integration (integration без сервисов — skipped)
```

## Структура проекта

```
nft-sniper/
├── src/nftsniper/
│   ├── bootstrap.py           # FastAPI-приложение: /healthz /readyz /metrics
│   ├── shared/
│   │   ├── domain/            # Entity, ValueObject, DomainEvent
│   │   └── money.py           # TON / nanoTON / USD, Decimal, не float
│   ├── contexts/
│   │   ├── sources/           # сбор листингов: domain/application/ports/adapters
│   │   ├── valuation/         # ядро: ансамбль оценки fair price
│   │   ├── risk/              # фильтры мусора и скамов
│   │   ├── alerts/            # матчинг, дедуп, доставка, решения
│   │   └── portfolio/         # опционально, после MVP
│   ├── infrastructure/
│   │   ├── database/          # async SQLAlchemy engine, сессии
│   │   ├── cache/             # Redis pool
│   │   ├── messaging/         # Redis Streams
│   │   └── http/              # общий клиент: retry, backoff, breaker
│   ├── entrypoints/
│   │   ├── bot/               # aiogram 3
│   │   ├── workers/           # poller, valuator, notifier, calibrator
│   │   └── cli/               # nftsniper serve | check | version
│   ├── config/                # Pydantic Settings (env-префикс NFT_)
│   └── observability/         # structlog-логи, Prometheus-метрики
├── migrations/                # alembic (async env.py)
├── scripts/no_float.py        # статический гейт: float запрещён в бизнес-коде
├── tests/{unit,integration,contract,backtest}/
├── docker-compose.yml         # postgres:16, redis:7 (+app через --profile full)
└── .github/workflows/ci.yml   # lint / unit / integration (с сервисами)
```

Подробности по каждому контексту — в README внутри `src/nftsniper/contexts/*/`.

## Конвенции

- **Деньги — только `Decimal` и nanoTON (`int`)**. `float` запрещён в бизнес-коде
  и преследуется статическим гейтом `scripts/no_float.py` (в whitelist — только
  `infrastructure/http` (секунды backoff) и `observability` (метрики)).
- **Hexagonal architecture**: домен не импортирует инфраструктуру;
  внешние источники — за портами (`MarketplacePort`, `ChainPort`, ...),
  адаптеры заменяемы на fake.
- **Pydantic v2 — только на границах** (settings, адаптеры, API). В домене —
  dataclass/value objects.
- **On-chain — источник истины** по ценам; API маркетплейсов — для скорости.
  Расхождение больше 1% помечается флагом.
- **Оценка всегда объяснима**: confidence + интервал (P25/P75), никогда одна цифра.
- mypy `strict = true`, ruff (см. `pyproject.toml`), таймстемпы — ISO 8601 UTC.

## Задачи по агентам (кратко, полное описание — в ТЗ §7)

| Агент | Что | Статус |
|---|---|---|
| 1 | Skeleton & Infra: каркас, pyproject, ruff/mypy strict, compose, settings, логи, health, CI | ✅ **этот коммит** |
| 2 | Domain & Ports: деньги, сущности, порты | ⬜ |
| 3 | GetGems Adapter | ⬜ |
| 4 | Chain Adapter (TonAPI/TonCenter) | ⬜ |
| 5 | Fragment Adapter | ⬜ |
| 6 | Statistics Engine (price_stats) | ⬜ |
| 7 | Valuation Engine (ансамбль) | ⬜ |
| 8 | Risk & Anti-Scam | ⬜ |
| 9 | Alert Engine | ⬜ |
| 10 | Telegram Bot (aiogram 3) | ⬜ |
| 11 | Feedback Loop & Analytics | ⬜ |
| 12 | Observability & Backtest | ⬜ |

**Фазы** (ТЗ §8): 1) MVP — 1,2,3,6,10 + упрощённая оценка; 2) качество — 4,7,8;
3) масштаб — 5,9,11; 4) зрелость — 12, портфель/PnL, бэктест как gate.
