# Контекст: sources

Сбор листингов, истории продаж, трейтов и floor.

| Слой | Содержимое | Кто строит |
|---|---|---|
| domain | Listing, Collection, Item, SaleEvent, NftTransfer, WalletInfo, SaleVerification, FragmentAsset, FragmentAuction |  |
| application | PollListings, IngestSale, BackfillHistory, VerifySales, PollFragment |  |
| ports | MarketplacePort, ChainPort, FragmentPort |  |
| adapters/getgems | листинги, продажи, трейты, floor (GraphQL) |  |
| adapters/tonapi | on-chain: владелец, трансферы, sale-контракты, возраст кошелька, сверка цен |  |
| adapters/fragment | номера/юзернеймы: сначала on-chain, парсинг — fallback |  |

Приоритет источников: on-chain (истина) > маркетплейс (скорость).

## GetGems Adapter

Реализация `MarketplacePort` поверх GraphQL GetGems:

- **запросы** — `adapters/getgems/queries.py` (закреплённый контракт, v1);
- **нормализация** — `adapters/getgems/normalizer.py` (защитное чтение полей:
  битая запись → `None` → конвейер логирует и пропускает, не роняя пачку);
- **транспорт** — `infrastructure.http` (`ResilientHttpClient`: retry с
  exponential backoff + circuit breaker, `TokenBucketRateLimiter` перед каждым
  запросом);
- **пагинация** — листинги: offset; продажи: offset + фильтр `since`/`until`
  (продажи newest-first);
- **`raw`** листинга хранит исходные узлы для аудита и сверки с chain (ТЗ §3).

Use cases зависят только от портов — адаптер заменяем на fake без изменений
(тесты: `tests/unit/test_sources_application.py`, `tests/contract/`).

### Публичный API GetGems

`api.getgems.io/graphql` теперь требует ключ официального public-api
(`https://getgems.io/public-api`, ключ в `NFT_GETGEMS_API_KEY`). Контракт
закреплён фикстурами `tests/fixtures/getgems/*.json`; при смене схемы:

```bash
NFT_GETGEMS_API_KEY=... \
python scripts/record_getgems_fixtures.py --collection EQ... --item EQ...
pytest tests/contract
```

## TonAPI Adapter

Реализация `ChainPort` поверх REST v2 TonAPI — on-chain источник истины
(ТЗ §3): владелец NFT, история трансферов, метаданные кошелька, сверка цены
продажи с маркетплейсом.

- **эндпоинты** — `GET /v2/nfts/{id}` (владелец), `GET /v2/nfts/{id}/history`
  (трансферы, `AccountEvents`), `GET /v2/accounts/{id}` + `/events` (статус,
  возраст, входящий объём);
- **нормализация** — `adapters/tonapi/normalizer.py` (защитное чтение: сумма
  продажи = максимальный `TonTransfer.amount` в событии, битая запись → skip);
- **транспорт** — `infrastructure.http` (retry + circuit breaker) и
  `TokenBucketRateLimiter`; авторизация `Authorization: Bearer <token>`;
- **сверка цен** — `verify_sales` сравнивает цену `SaleEvent` с on-chain
  трансфером (окно ±`tonapi_sale_window_seconds`), расхождение больше
  `tonapi_price_mismatch_tolerance` (1%) помечается `SaleVerification.matches=False`;
  `VerifySales` (application) берёт детерминированную выборку до 100 сделок
  и возвращает расхождения отдельно (критерий готовности);
- 404 на NFT трактуется как «предмет не существует» → `None`.

Контракт закреплён фикстурами `tests/fixtures/tonapi/*.json`; при смене схемы:

```bash
NFT_TONAPI_KEY=... \
python scripts/record_tonapi_fixtures.py --nft 0:hex... --wallet 0:hex...
pytest tests/contract/test_tonapi_adapter.py
```

## Fragment Adapter

Реализация `FragmentPort` для Telegram-юзернеймов и анонимных номеров
(маркетплейс TON Foundation). Юзернеймы и номера — NFT на TON, поэтому
on-chain — источник истины (ТЗ §3).

- **on-chain первичен** (`prefer_on_chain=True`): существование, имена,
  владельцы и реальные цены продаж — TonAPI (`/v2/nfts/collections/{id}/items`
  + `/v2/nfts/_bulk` для имён, `ChainPort.get_nft_transfers` для продаж);
- **парсинг fragment.com — fallback/дополнение** (`scraper.py`): текущие
  ставки/цены аукционов, статусы (Resale/Sold/…), время конца — защитное
  чтение HTML (смена вёрстки → пустой результат, не исключение);
- **деградация**: `list_auctions` не роняет конвейер — при сбое парсинга
  отдаёт on-chain лоты без цен, при сбое on-chain — только scrape-лоты;
- **частота ограничена** `TokenBucketRateLimiter` (по умолчанию 0.5 rps) и
  TTL-кэш страниц (`fragment_cache_ttl_seconds`);
- **источник отключается флагом** `fragment_enabled=false` — ноль запросов
  (критерий готовности); `PollFragment` (application) ловит
  `FragmentError` и изолирует падение источника от остальных.

ToS: публичный HTML fragment.com читается без логина, с ограниченной частотой
и кэшем; данные коллекций также доступны через on-chain индексер (ТЗ §3).

```bash
# реестр коллекций задаётся настройками:
#   NFT_FRAGMENT_USERNAME_COLLECTION=0:…  NFT_FRAGMENT_NUMBER_COLLECTION=0:…
# перезапись фикстур при смене вёрстки/схемы:
NFT_TONAPI_KEY=... \
python scripts/record_fragment_fixtures.py --usernames 0:hex... --numbers 0:hex...
pytest tests/contract/test_fragment_adapter.py
```
