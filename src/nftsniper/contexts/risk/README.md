# Контекст: risk

Без этого блока бот присылает «скидку 90%» на скам-коллекции целыми
пачками. Обязателен ещё на фазе 2. Цель: на подготовленном наборе
скам-кейсов ловится >= 90% при контролируемых ложных срабатываниях.

## Идея

Детекторы — **чистые функции** (без I/O, только `Decimal`/`int`/`str`/
`datetime`), каждый возвращает один `RiskFlag` с кодом и severity
(`low`/`medium`/`high` → 0.2/0.5/0.9). Use case `ScreenListing` собирает
факты через порты и агрегирует их в `RiskScore` (0..1): сумма severity с
потолком 1.0, `score.passes(threshold)` — правило пропуска листинга в
алерт (ТЗ §4: алерт уходит только если `risk_score <= порог`).

## Детекторы

| Код | Что ловит | Severity |
|---|---|---|
| `CLONE_COLLECTION` | свежий клон: unicode-подмены (гомоглифы кириллица/греческий → латиница) + `SequenceMatcher` на нормализованных именах | high |
| `LOW_VOLUME` | < 3 продаж за 30 дней — это не рынок | medium |
| `BROKEN_METADATA` | пустое/пробельное имя предмета или недоступное медиа (HEAD по `media_url`) | high |
| `FRESH_SELLER` | кошелёк продавца младше 7 дней | high |
| `UNKNOWN_SELLER` | возраст продавца неизвестен (не проверить) | medium |
| `FAKE_SALES` | продажа выше `медиана × 10` — раздутая история | high |
| `WASH_TRADING` | короткий цикл (<= 3 рёбер) A→B→…→A в графе сделок предмета, окно 2 дня | high |
| `AUCTION_MISMATCH` | цена — текущая ставка аукциона, сравнивать с fixed некорректно | medium |
| `ROYALTY_IMPACT` | `net = price − royalty − комиссия`; flag если комиссии съедают > 20% | low |

Пороги по умолчанию и гомоглифная карта — в `application/detectors.py`,
переопределяются через `RiskConfig`.

## Структура

- `domain/risk.py` — `RiskFlag`, `RiskSeverity`, `RiskScore` (агрегат 0..1,
  `with_flag`, `passes`, `worst_severity`).
- `ports.py` — `CollectionCatalogPort.known_collections()`,
  `MediaPort.is_available(url)` (единственные внешние факты скрининга).
- `application/detectors.py` — чистые детекторы (без I/O).
- `application/screen.py` — `compute_risk` (чистая агрегация) и
  `ScreenListing` (use case: chain/каталог/медиа/продажи через порты).
- `adapters/media.py` — `HttpMediaChecker` (`MediaPort` поверх
  `ResilientHttpClient`, HEAD-запрос).

## Инварианты

- Все детекторы детерминированы; `Decimal`-only, `float` запрещён
  (`scripts/no_float.py` в CI).
- Гексагональность: use case знает только порты, не HTTP/БД напрямую.
- `compute_risk` не делает I/O → легко тестируется на скам-фикстурах
  (`tests/unit/test_risk_scam_dataset.py`).

## Acceptance

`tests/unit/test_risk_scam_dataset.py` гоняет подготовленный набор
(11 скам-кейсов + 10 чистых) через `compute_risk`: recall >= 0.9,
ложных срабатываний 0.
