# Контекст: alerts

Матчинг листингов с настройками пользователей, дедупликация, rate limit,
quiet hours, приоритизация (сначала лучшие сделки). Решения пользователя
(taken/skipped/watch/muted) записываются для калибровки модели.

## Что готово

- **Домен** (`domain/alert.py`): Alert, Decision, AlertButton (callback или url),
  AlertMessage, AlertPolicy (условия алерта ТЗ §4). Кнопка-ссылка — диплинк
  на маркетплейс (ТЗ §1: «Взять» не покупает).
- **Порты** (`ports/__init__.py`): NotifierPort (send/edit), AlertRepository,
  DecisionRepository.
- **Адаптер Telegram** (`adapters/telegram/notifier.py`): `TelegramNotifier` —
  отправка и редактирование алертов (parse_mode HTML), `build_inline_keyboard`.

## Что готово (— Alert Engine)

- **Домен**:
  - `AlertPolicy.quiet_hours` (окна тишины, часы UTC, могут пересекать полночь)
    + `is_quiet(now)`; валидация часов в [0, 23].
  - `candidate.py`: `Subscriber` (user_id + AlertPolicy + язык + пауза),
    `ListingScore` (сводка оценённого листинга для notifier — риск в плоских
    значениях, без зависимости alerts → risk), `AlertCandidate` (прошедший
    матчинг, готовый к рендеру).
- **Порты**: `AlertRepository.count_recent` (rate limit),
  `AlertRepository.find_recent_by_dedup` (дедуп, окно из политики),
  `SubscriberDirectory` (список подписчиков).
- **Application**:
  - `matcher.py` — чистый матчинг: `match_listing` (пауза → quiet hours →
    пороги `AlertPolicy.allows` → `AlertCandidate`) и `candidate_priority`
    (дискаунт ×10 + уверенность, Decimal).
  - `engine.py` — `AlertEngine.deliver/deliver_batch`: матчинг →
    пер-пользовательский top-K по бюджету (max_alerts_per_hour) →
    глобальный max-heap по приоритету → доставка с дедупом и rate limit.
    Всплеск 1000 листингов/мин ограничен бюджетами: отправляется не больше
    лимита на человека, очередь не раздувается.
  - `decisions.py` — `RecordDecision`: каноническая запись решения +
    `DecisionRecorded` для калибровки.
- **Мостик бота** (`entrypoints/bot/`): `UserSettings.quiet_hours` пробрасывается
  в `alert_policy()`; `UserSettingsStore.list_users()`; адаптер
  `SubscriberDirectoryFromSettings`; `render_candidate` (AlertCandidate →
  сообщение алерта) — рендер движка.

## Acceptance

`tests/unit/test_alert_engine.py`: нет дублей (дедуп по (user, dedup_key) в
окне), лимиты соблюдаются (не более max_alerts_per_hour в час, с учётом уже
отправленных), всплеск 1000 листингов → отправляется ровно бюджет, лучшие
сделки уходят первыми.

## Что готово (— Feedback Loop & Analytics)

- **Домен** (`domain/outcome.py`): `Outcome` — исход алерта (таблица
  `outcomes`, ТЗ §5): цены по окнам 1h/24h/7d, факт продажи, база для
  precision. Методы: `apply_snapshot` (окно), `mark_sold`, `final_price`
  (продажа > 24h > 7d > 1h > цена алерта), `confirmed_24h` (fair подтвердился
  ± tolerance), `is_winning` (цена выросла). `OutcomeWindow` = 1h/24h/7d.
- **Порты**: `OutcomeRepository` (save/get_by_alert/list_by_user);
  `AlertRepository.list_by_user`, `DecisionRepository.list_by_user`.
- **Application**:
  - `outcome_tracking.py` — `TrackOutcome`: фиксирует состояние листинга в
    окне или продажу; первый снимок создаёт Outcome.
  - `analytics.py` — чистые функции + use case `AlertAnalytics`:
    - `compute_quality` → `QualityReport`: precision (доля алертов, где fair
      подтвердился), take rate (доля «Взять»), hit rate (цена выросла),
      средний дискаунт;
    - `compute_counterfactual` → `CounterfactualReport`: «что было бы, если
      бы вы взяли все алерты» — потрачено/стоимость/PnL/упущенное;
    - `recommend_threshold` → `ThresholdRecommendation`: персональная
      рекомендация `min_discount` — наименьший порог, где precision ≥ цели
      при достаточной выборке; фолбэк — порог с максимальной precision;
      без данных — текущий порог.
- **Критерий готовности ТЗ §7**: качество видно в цифрах и есть рекомендация
  порога для конкретного пользователя (`tests/unit/test_analytics.py`).

## Дальше

- Postgres/Redis-реализации репозиториев и SubscriberDirectory;
- `/stats` бота может переехать на `AlertAnalytics` (пока — InMemoryDecisionStore).

Конвейер `poll → score → risk → notify` собран в
`entrypoints/workers/pipeline.py` (`ListingPipeline`);
outcome-tracker (TrackOutcome) и calibrator — отдельные воркеры, см.
`entrypoints/workers/README.md`.
