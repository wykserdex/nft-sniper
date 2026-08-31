# Контекст: sources

Сбор листингов, истории продаж, трейтов и floor.

| Слой | Содержимое | Кто строит |
|---|---|---|
| domain | Listing, Collection, Item, SaleEvent, TraitSet |  |
| application | PollListings, IngestSale, BackfillHistory |  |
| ports | MarketplacePort, ChainPort |  |
| adapters/getgems | листинги, продажи, трейты, floor (GraphQL) |  |
| adapters/tonapi, tonx | on-chain: трансферы, sale-контракты, возраст кошелька |  |
| adapters/fragment | номера/юзернеймы: сначала on-chain, парсинг — fallback |  |

Приоритет источников: on-chain (истина) > маркетплейс (скорость).
