# ТЗ: Telegram-бот для поиска недооценённых NFT на TON

Бот не покупает. Он находит, оценивает, объясняет и спрашивает. Решение всегда за человеком.

---

## 1. Продуктовая суть

```
Новый листинг → Оценка справедливой цены → Расчёт дискаунта
  → Если дисконт > порога → Алерт в Telegram
  → Кнопки: Купить / Скип / Позже / Заглушить коллекцию
  → Решение записывается → используется для калибровки модели
```

Пример алерта:

```
🔥 Deal 42%

Anonymous Telegram Number #888
Коллекция: Anonymous Numbers
Цена: 120 TON  (~$580)
Fair price: 207 TON
Дискаунт: -42%

Floor: 195 TON  (24h: -3%)
Median 7d: 214 TON  (18 продаж)
Rarity: топ 8% по коллекции
Ликвидность: 2.4 продажи/день
Возраст листинга: 11 сек

Уверенность оценки: 0.78  (высокая)
⚠️ Флаг: продавец создан 2 дня назад

[ ✅ Взять ]  [ ❌ Скип ]  [ 🔔 Следить ]  [ 🔇 Мьют коллекции ]
[ 🔗 Открыть на GetGems ]
```

Нажатие «Взять» не покупает, а даёт диплинк на маркетплейс и логирует интент.

---

## 2. Архитектура

```
nft-sniper/
├── src/nftsniper/
│   ├── bootstrap.py
│   │
│   ├── shared/
│   │   ├── domain/          # Entity, ValueObject, DomainEvent
│   │   └── money.py         # TON / nanoTON / USD, Decimal, никогда float
│   │
│   ├── contexts/
│   │   ├── sources/         # сбор листингов
│   │   │   ├── domain/      # Listing, Collection, SaleEvent, TraitSet
│   │   │   ├── application/ # PollListings, IngestSale, BackfillHistory
│   │   │   ├── ports/       # MarketplacePort, ChainPort
│   │   │   └── adapters/
│   │   │       ├── getgems/
│   │   │       ├── fragment/
│   │   │       ├── tonapi/
│   │   │       └── tonx/
│   │   │
│   │   ├── valuation/       # ядро проекта
│   │   │   ├── domain/      # FairPrice, Confidence, Discount, Liquidity
│   │   │   ├── application/ # EstimateFairPrice, ScoreListing, Calibrate
│   │   │   ├── ports/       # PriceModelPort, FeatureStorePort
│   │   │   └── adapters/
│   │   │       ├── floor_model.py
│   │   │       ├── trait_model.py
│   │   │       └── ensemble.py
│   │   │
│   │   ├── risk/            # фильтры мусора и скамов
│   │   │   ├── domain/      # RiskFlag, RiskScore
│   │   │   └── application/ # ScreenListing, DetectWashTrading
│   │   │
│   │   ├── alerts/
│   │   │   ├── domain/      # Alert, Decision, AlertPolicy
│   │   │   ├── application/ # BuildAlert, DeliverAlert, RecordDecision
│   │   │   └── adapters/    # telegram/
│   │   │
│   │   └── portfolio/       # опционально, после MVP
│   │       └── application/ # TrackWatchlist, PnLReport
│   │
│   ├── infrastructure/
│   │   ├── database/        # PostgreSQL + TimescaleDB/партиции
│   │   ├── cache/           # Redis: floor, dedup, rate limit
│   │   ├── messaging/       # Redis Streams / NATS
│   │   └── http/            # общий клиент: retry, backoff, circuit breaker
│   │
│   ├── entrypoints/
│   │   ├── bot/             # aiogram 3: handlers, keyboards, FSM настроек
│   │   ├── workers/         # poller, valuator, notifier, calibrator
│   │   └── cli/
│   │
│   ├── config/
│   └── observability/
│
├── migrations/
├── tests/
│   ├── unit/ integration/ contract/ backtest/
└── pyproject.toml
```

Стек: Python 3.12, aiogram 3, SQLAlchemy 2.0 async, PostgreSQL, Redis, httpx, Pydantic v2 (только на границах), pytest, ruff, mypy strict.

---

## 3. Источники данных

| Источник | Что даёт | Как брать | Сложность |
|---|---|---|---|
| **GetGems** | листинги, история продаж, трейты, floor | публичный GraphQL API | средняя |
| **TON blockchain** | NFT-трансферы, sale-контракты, реальные цены | TonAPI / TonCenter / индексер | средняя |
| **Fragment** | номера, юзернеймы, аукционы | нет публичного API, нужен парсинг HTML | высокая |
| **Telegram Gifts** | подарки и их floor | Bot API + маркеты | средняя |
| **Курс TON/USD** | нормализация | CoinGecko / Binance | низкая |

Важно: on-chain — источник истины по ценам. API маркетплейса используется для скорости, chain — для верификации. Расхождение больше 1% помечается флагом.

По Fragment: перед парсингом проверить ToS и robots.txt, ограничить частоту, не логиниться под чужими сессиями. Если парсинг рискован — брать данные Fragment-коллекций через on-chain индексер, там они тоже видны.

---

## 4. Модель оценки справедливой цены

Это то, где живёт вся ценность продукта. Наивная схема «цена ниже floor = сделка» даёт 90% ложных срабатываний.

Ансамбль оценок:

```python
@dataclass(frozen=True, slots=True)
class FairPriceEstimate:
    value: TON
    confidence: Decimal          # 0..1
    method: EstimationMethod
    lower_bound: TON             # 25-й перцентиль
    upper_bound: TON             # 75-й перцентиль
    sample_size: int
    explanation: list[str]       # человекочитаемые причины
```

Компоненты:

1. **Floor-based** — устойчивый floor как перцентиль (P5 активных листингов), а не минимум. Один мусорный листинг не должен ронять floor.
2. **Comparable sales** — медиана продаж похожих предметов за 7–30 дней с временным затуханием (полураспад ~7 дней).
3. **Trait/rarity model** — для коллекций с признаками. Простая регрессия или градиентный бустинг на log(price), признаки: редкость трейтов, длина/паттерн номера, повторяющиеся цифры, категория.
4. **Collection momentum** — тренд floor и объёма за 24h/7d. На падающем рынке fair price занижается.

Итог — взвешенное среднее, где веса зависят от размера выборки и свежести данных.

Дискаунт и порог:

```
discount = (fair_price - listing_price) / fair_price
```

Алерт отправляется, если одновременно:

- discount >= порог пользователя (по умолчанию 25%);
- confidence >= 0.5;
- liquidity_score >= минимум (продаваемость важнее самой скидки);
- risk_score <= максимум;
- цена в абсолютном диапазоне пользователя;
- нет дубликата за окно дедупликации.

Обязательные фильтры мусора:

- Wash trading: кольцевые продажи между связанными кошельками.
- Свежесозданные коллекции-клоны с похожим названием и подменённым символом.
- Коллекции без реального объёма: 3 продажи за месяц — не рынок.
- Битые/пустые метаданные, недоступный IPFS.
- Явно завышенные fake-продажи в истории, поднимающие «fair price».
- Аукционы против фиксированной цены: сравнивать только сопоставимые типы.
- Роялти и комиссия маркетплейса, включённые в расчёт реального выхода.

Без этого блока бот будет присылать «скидку 90%» на скам-коллекции целыми пачками.

---

## 5. Данные

```sql
collections(id, address, name, slug, marketplace, verified,
            created_at, items_count, risk_score)

items(id, collection_id, address, index, name, traits jsonb,
      rarity_rank, rarity_score)

listings(id, item_id, marketplace, price_nano, currency, seller,
         listed_at, closed_at, status, raw jsonb)

sales(id, item_id, price_nano, buyer, seller, tx_hash,
      sold_at, marketplace, is_suspicious)

price_stats(collection_id, ts, floor_p5, median_7d, volume_24h,
            sales_per_day, listings_count)   -- time-series

valuations(id, listing_id, fair_price_nano, discount, confidence,
           method, model_version, features jsonb, created_at)

alerts(id, user_id, listing_id, valuation_id, sent_at,
       message_id, dedup_key)

decisions(id, alert_id, user_id, action, latency_ms, created_at)
          -- action: taken | skipped | watch | muted

outcomes(id, alert_id, price_after_1h, price_after_24h,
         sold_at, sold_price, computed_at)   -- была ли сделка реально хорошей

user_settings(user_id, min_discount, min_confidence, price_min, price_max,
              collections_whitelist, collections_blacklist,
              quiet_hours, max_alerts_per_hour, language)
```

Индексы: GIN на traits, партиционирование sales и price_stats по времени, уникальный индекс на (marketplace, listing_external_id) для идемпотентности.

---

## 6. Поток обработки

```
Poller (2–5 сек)
  → нормализация листинга
  → dedup по content hash
  → publish ListingDiscovered

Valuator (consumer)
  → загрузка признаков и статистики коллекции
  → ансамбль оценки
  → risk screening
  → publish ListingScored

Notifier (consumer)
  → матчинг с настройками пользователей
  → проверка порогов, quiet hours, rate limit
  → рендер алерта + inline keyboard
  → отправка, запись Alert

Decision handler
  → callback от кнопки
  → запись Decision, обновление сообщения
  → мьют / вотчлист / диплинк

Outcome tracker (через 1h / 24h / 7d)
  → что стало с листингом
  → метрики precision алертов

Calibrator (ночью)
  → переобучение весов ансамбля
  → отчёт качества, дрейф модели
```

Задержка от появления листинга до алерта — цель менее 3 секунд. Это ключевая метрика: выгодные листинги забирают за секунды.

---

## 7. Разбивка на задачи для ИИ-агентов

Каждая задача самодостаточна: свой контракт, свои тесты, минимум пересечений.

** — Skeleton & Infra**
Каркас проекта, pyproject, ruff/mypy strict, docker-compose (Postgres, Redis), settings через Pydantic Settings, структурные логи, health-эндпоинт, CI.
Готово когда: docker compose up поднимает окружение, линт и тесты зелёные.

** — Domain & Ports**
Доменные сущности и value objects: TON на Decimal и nanoTON, Listing, Collection, Item, SaleEvent, FairPriceEstimate, Discount, RiskFlag. Протоколы MarketplacePort, ChainPort, PriceModelPort, NotifierPort, репозитории. Доменные события.
Готово когда: домен не импортирует ничего из infrastructure, покрыт unit-тестами арифметики денег.

** — GetGems Adapter**
Реализация MarketplacePort: листинги, история продаж, трейты, floor. Пагинация, retry с exponential backoff, circuit breaker, rate limit, нормализация в доменные модели.
Готово когда: контрактные тесты на записанных фикстурах проходят, адаптер заменяем на fake без изменений в use cases.

** — Chain Adapter**
ChainPort через TonAPI/TonCenter: NFT-трансферы, sale-контракты, реальные цены сделок, верификация владельца, проверка возраста кошелька продавца. Сверка с данными маркетплейса.
Готово когда: on-chain цена совпадает с API-ценой на выборке из 100 сделок, расхождения помечены.

** — Fragment Adapter**
Номера и юзернеймы: цены, аукционы, состояние. Сначала попытка через on-chain данные, парсинг только как fallback. Строгие лимиты частоты, кэш, устойчивость к смене вёрстки, чёткая деградация при недоступности.
Готово когда: источник можно отключить флагом, падение источника не ломает остальные.

** — Statistics Engine**
Расчёт price_stats: устойчивый floor как P5, медианы с временным затуханием, объёмы, sales_per_day, liquidity score, momentum floor 24h/7d. Инкрементальный пересчёт, окна, партиционирование.
Готово когда: пересчёт коллекции из 10k предметов укладывается в SLA, значения совпадают с эталонным расчётом на фикстурах.

** — Valuation Engine**
Ансамбль: floor-модель, comparable sales, trait-модель, momentum. Расчёт confidence и границ интервала. Версионирование модели, сохранение признаков в valuations для аудита. Человекочитаемое объяснение оценки.
Готово когда: на историческом бэктесте медианная ошибка ниже согласованного порога и оценка всегда объяснима.

** — Risk & Anti-Scam**
Детектор wash trading по графу кошельков, определение коллекций-клонов и unicode-подмен, фильтр коллекций без объёма, проверка метаданных и доступности медиа, возраст и история продавца, учёт роялти и комиссий в реальном выходе.
Готово когда: на подготовленном наборе скам-кейсов ловится не менее 90% при контролируемом уровне ложных срабатываний.

** — Alert Engine**
Матчинг листингов с настройками пользователей, дедупликация, rate limit на пользователя, quiet hours, приоритизация: при потоке сначала уходят лучшие сделки. Рендер сообщения и inline-клавиатуры.
Готово когда: нет дублей, лимиты соблюдаются, при всплеске 1000 листингов/мин очередь не деградирует.

** — Telegram Bot**
aiogram 3: /start, /settings с FSM, /watchlist, /stats, /mute, /pause. Обработка callback-кнопок, редактирование сообщения после решения, диплинки на маркетплейс, локализация RU/EN, приватные изображения предметов.
Готово когда: полный путь настройки и реакции на алерт проходится без ошибок, ответ на callback быстрее 1 секунды.

** — Feedback Loop & Analytics**
Запись решений и латентности, трекинг исходов через 1h/24h/7d, метрики precision и hit rate, персональная калибровка порогов под пользователя, отчёт «что было бы, если бы вы взяли все алерты».
Готово когда: видно качество алертов в цифрах и рекомендация по порогу для конкретного пользователя.

** — Observability & Backtest**
Prometheus-метрики: задержка pipeline, срабатывания rate limit, ошибки источников, размер очередей. Алерты на деградацию. Фреймворк бэктеста на исторических данных для проверки изменений модели перед деплоем.
Готово когда: любое изменение valuation прогоняется через бэктест и даёт сравнимый отчёт.

---

## 8. Порядок работ

- **Фаза 1, MVP.**  плюс упрощённая valuation: floor P5 и медиана 7d. Один маркетплейс, один пользователь, простой порог. Цель — увидеть первые живые алерты.
- **Фаза 2, качество.**. On-chain верификация, ансамбль, анти-скам. Здесь количество мусорных алертов должно упасть в разы.
- **Фаза 3, масштаб.**. Fragment, много пользователей, обратная связь и калибровка.
- **Фаза 4, зрелость.**, портфель и PnL, бэктест как gate для деплоя.

---

## 9. Риски и как их закрыть

| Риск | Ответ |
|---|---|
| API маркетплейса меняется или блокирует | адаптеры за портами, контрактные тесты, on-chain как fallback |
| Скам-коллекции выглядят как супер-сделки | risk-модуль обязателен ещё в фазе 2, не позже |
| Шумные алерты, пользователь отключает бота | приоритизация, rate limit, калибровка по решениям |
| Ошибки округления в деньгах | только Decimal и nanoTON, float запрещён на уровне линтера |
| Задержка выше 3 секунд, сделки уходят | измерять latency по этапам, кэшировать статистику заранее |
| Дубли алертов при рестарте | idempotency key и dedup в Redis с TTL |
| Юридические вопросы по парсингу | проверить ToS каждого источника, лимитировать частоту, предпочитать официальные API и on-chain |
| Иллюзия точности оценки | всегда показывать confidence и интервал, никогда одну цифру |

---

## 10. Метрики успеха

- **Precision алертов**: доля сделок, где через 24h fair price подтвердился.
- **Latency p95** от появления листинга до доставки алерта.
- **Take rate**: доля алертов, по которым пользователь нажал «Взять».
- **Скам-пропуски**: сколько мусорных алертов дошло до пользователя.
- **Ошибка оценки**: MAPE fair price против фактических продаж.
