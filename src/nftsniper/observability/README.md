# Observability

Логи (structlog) и Prometheus-метрики + алерты деградации.

## Метрики (`metrics.py`)

Полный каталог (ТЗ §12): счётчики ingestion/алертов, latency пайплайна по
этапам (`poller`/`valuate`/`risk`/`match`/`notify`), размеры очередей,
срабатывания rate limit/фильтров, ошибки источников
(`getgems`/`tonapi`/`fragment`), алерты деградации.

Метрики с метками заполняются через helper'ы:

- `observe_stage(stage, seconds)` — задержка этапа;
- `set_queue_size(queue, size)` — размер очереди;
- `hit_rate_limit(kind)` — dedup/rate_limit/quiet;
- `record_source_error(source, kind)` — ошибка источника;
- `record_degradation_alert(rule)` — срабатывание алерта деградации.

Здесь измеряются физические величины (секунды, счётчики), поэтому float
допустим: `observability` — в whitelist'е no-float (деньги остаются Decimal).

## Алерты деградации (`degradation.py`)

`check_degradation(HealthSnapshot, thresholds) -> tuple[DegradationAlert, ...]`
— чистая функция: глубина очередей, ошибки источников/мин, срабатывания
rate limit/мин, latency p95 оценка/доставка. Пороги — `DegradationThresholds`
(переопределяемы); severity `warning`/`critical`. `emit_degradation_alerts`
связывает алерты с `nft_sniper_degradation_alerts_total{rule=...}`.

Воркеры (poller/valuator/notifier) привязывают вызовы helper'ов к своим
этапам и раз в N секунд пишут снимок очередей в `set_queue_size`.
