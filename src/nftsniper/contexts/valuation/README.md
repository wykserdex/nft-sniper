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
