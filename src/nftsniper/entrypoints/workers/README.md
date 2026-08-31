# Воркеры

Конвейер обработки листингов (ТЗ §6): poll → score → risk → notify.

## ListingPipeline

`pipeline.py` — `ListingPipeline.run(collection_address, limit)` склеивает
готовые use cases в один проход по новым листингам:

1. `PollListings` — новые листинги (дедуп по dedup_key);
2. признаки коллекции из фич-стора (`RebuildStats` при отсутствии);
3. `ScoreListing` — fair price, confidence, discount;
4. `ScreenListing` — risk-скрининг (wash trading, клоны, объём, ...);
5. сборка `ListingScore` → `AlertEngine.deliver` (матчинг, дедуп,
   rate limit, приоритизация, доставка).

Итог — `PipelineReport`: discovered / scored / risk_flagged / matched /
delivered / dropped. Это чистая оркестрация поверх портов — тестируется
end-to-end на fake'ах (`tests/unit/test_pipeline.py`).

`getgems_item_url(address)` — диплинк предмета для кнопки
«Открыть на GetGems» (ТЗ §1).

## Осталось (production)

- wiring на реальных адаптерах (GetGems/TonAPI/Fragment + Postgres/Redis
  репозитории) и цикл по расписанию 2–5 сек;
- привязка метрик (`observability/metrics.py`): `observe_stage`,
  `set_queue_size`, `hit_rate_limit`, `record_source_error`;
- outcome-tracker (TrackOutcome 1h/24h/7d) и ночной calibrator.
