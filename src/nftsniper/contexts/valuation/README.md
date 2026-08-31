# Контекст: valuation — ядро проекта

Наивная схема «цена ниже floor = сделка» даёт 90% ложных срабатываний,
поэтому оценка — ансамбль: floor P5, comparable sales с затуханием
(полураспад ~7 дней), trait-модель, collection momentum.

Алерт только если: discount >= порога (дефолт 25%), confidence >= 0.5,
liquidity ок, risk ок, цена в диапазоне пользователя, нет дубля.
См. ТЗ §4.

## Statistics Engine

`application/stats.py` — чистая математика на Decimal (без float), это и
эталонный расчёт для тестов, и рантайм-пересчёт:

- `floor_p5` — устойчивый floor: nearest-rank перцентиль P5 активных
  листингов (один мусорный листинг не роняет floor, ТЗ §4);
- `decayed_sales_median` / `time_decayed_median` — медиана продаж за 7 дней
  с временным затуханием (полураспад 7 дней): свежие продажи весят больше;
- `volume`, `sales_per_day`, `sales_in_window` — объёмы и темп за 24h/7d;
- `floor_change` + `append_floor_snapshot` — momentum floor 24h/7d по
  дневной истории (снимок того же дня заменяется);
- `normalize_liquidity` — нормированный скор 0..1: `min(1, spd / target)`,
  target по умолчанию 5 продаж/день (продаваемость важнее скидки, ТЗ §4);
- `compute_collection_stats` — сводный пересчёт в `CollectionFeatures` +
  `LiquidityScore`. Нет продаж за 7 дней → median откатывается на floor,
  ликвидность = 0 (такие коллекции отсеет минимум ликвидности в алертах).

`application/rebuild_stats.py` — use case `RebuildStats`: читает активные
листинги и продажи из репозиториев, пересчитывает статистику и сохраняет в
`FeatureStorePort`; инкрементальный режим продлевает дневную историю floor
из предыдущего снимка.

SLA: пересчёт коллекции из 10k предметов — десятки миллисекунд
(см. `tests/unit/test_stats.py::test_recompute_10k_items_within_sla`).

## Valuation Engine

Ансамбль из четырёх компонент (ТЗ §4) в `adapters/`:

- **floor_model** — устойчивый floor (P5 активных листингов из),
  вес по числу листингов, интервал ±10%;
- **comparable_sales** — медиана продаж 7d с затуханием, вес по
  числу продаж, интервал шире при малой выборке;
- **trait_model** — прозрачная rarity-модель: сигнал редкости 0..1 (по
  трейтам `rarity` либо `rarity_rank`), множитель 0.75–1.5 к baseline;
- **momentum** — тренд floor за 7 дней: падающий рынок занижает fair price
  (`×clamp(1 + change, 0.5, 1.5)`).

`adapters/ensemble.py` — `EnsemblePriceModel` (адаптер `PriceModelPort`):

- **value** — взвешенное среднее компонент (веса = номинальный вес × качество
  данных), затем поправка momentum;
- **interval** — P25/P75 точечных оценок (ТЗ §4: «никогда одну цифру»);
- **confidence** — покрытие данных × согласие компонент (0..1);
- **model_version** (`7.0.0`) и **explanation** — человекочитаемые причины,
  сохраняются в valuations для аудита (ТЗ §5).

Use cases в `application/`: `EstimateFairPrice` (оценка + сохранение),
`ScoreListing` (оценка + `Discount` + событие `ListingScored` для конвейера),
`run_backtest` (walk-forward бэктест без look-ahead: медианная ошибка fair
price против фактических продаж).

Критерий готовности  (ТЗ §7): на синтетической истории из 24 продаж
медианная ошибка ≈ 8% при пороге 40% и оценка всегда объяснима
(`tests/unit/test_backtest.py`).
