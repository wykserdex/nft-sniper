"""Fake-реализации портов для контрактных и юнит-тестов.

Критерий: «адаптер заменяем на fake без изменений в use cases».
Эти fake'и реализуют те же протоколы, что и GetGemsAdapter, и используются
в тестах use cases (PollListings / IngestSale / BackfillHistory).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from nftsniper.contexts.sources.domain.chain import NftTransfer, SaleVerification, WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.fragment import FragmentAsset, FragmentAuction
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.sources.ports.fragment import FragmentError
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures


class FakeMarketplacePort:
    """MarketplacePort в памяти: данные задаются списками, вызовы логируются."""

    def __init__(
        self,
        *,
        collections: Sequence[Collection] = (),
        items: Sequence[Item] = (),
        listings: Sequence[Listing] = (),
        sales: Sequence[SaleEvent] = (),
    ) -> None:
        self.collections: list[Collection] = list(collections)
        self.items: list[Item] = list(items)
        self.listings: list[Listing] = list(listings)
        self.sales: list[SaleEvent] = list(sales)
        self.listings_calls: list[tuple[str | None, int]] = []
        self.sales_calls: list[tuple[str, datetime, int, datetime | None]] = []

    async def get_collection(self, address: str) -> Collection | None:
        for collection in self.collections:
            if collection.id == address:
                return collection
        return None

    async def get_item(self, address: str) -> Item | None:
        for item in self.items:
            if item.id == address:
                return item
        return None

    async def list_active_listings(
        self,
        collection_address: str | None = None,
        limit: int = 100,
    ) -> Sequence[Listing]:
        self.listings_calls.append((collection_address, limit))
        selected = [
            listing
            for listing in self.listings
            if listing.is_active
            and (collection_address is None or listing.item.collection_id == collection_address)
        ]
        return selected[:limit]

    async def get_sales(
        self,
        collection_address: str,
        since: datetime,
        limit: int = 500,
        until: datetime | None = None,
    ) -> Sequence[SaleEvent]:
        self.sales_calls.append((collection_address, since, limit, until))
        selected = [
            sale
            for sale in self.sales
            if sale.collection_id == collection_address
            and sale.sold_at >= since
            and (until is None or sale.sold_at <= until)
        ]
        selected.sort(key=lambda sale: sale.sold_at, reverse=True)
        return selected[:limit]


class InMemoryListingRepository:
    """ListingRepository в памяти (upsert по id, поиск по dedup_key)."""

    def __init__(self) -> None:
        self._data: dict[str, Listing] = {}

    async def save(self, listing: Listing) -> None:
        self._data[listing.id] = listing

    async def get(self, listing_id: str) -> Listing | None:
        return self._data.get(listing_id)

    async def get_by_dedup_key(self, dedup_key: str) -> Listing | None:
        for listing in self._data.values():
            if listing.dedup_key == dedup_key:
                return listing
        return None

    async def list_active(
        self, collection_id: str | None = None, limit: int = 200
    ) -> Sequence[Listing]:
        selected = [listing for listing in self._data.values() if listing.is_active]
        if collection_id is not None:
            selected = [
                listing for listing in selected if listing.item.collection_id == collection_id
            ]
        return selected[:limit]


class InMemorySaleRepository:
    """SaleRepository в памяти (add, get, выборки по item/collection)."""

    def __init__(self) -> None:
        self._data: dict[str, SaleEvent] = {}

    async def get(self, sale_id: str) -> SaleEvent | None:
        return self._data.get(sale_id)

    async def add(self, sale: SaleEvent) -> None:
        self._data[sale.id] = sale

    async def list_by_item(self, item_id: str, since: datetime) -> Sequence[SaleEvent]:
        return [
            sale
            for sale in self._data.values()
            if sale.item_id == item_id and sale.sold_at >= since
        ]

    async def list_by_collection(
        self, collection_id: str, since: datetime, limit: int = 1000
    ) -> Sequence[SaleEvent]:
        selected = [
            sale
            for sale in self._data.values()
            if sale.collection_id == collection_id and sale.sold_at >= since
        ]
        selected.sort(key=lambda sale: sale.sold_at, reverse=True)
        return selected[:limit]


class InMemoryFeatureStore:
    """FeatureStorePort в памяти: снимки price_stats по collection_id."""

    def __init__(self) -> None:
        self._data: dict[str, CollectionFeatures] = {}

    async def load(self, collection_id: str) -> CollectionFeatures | None:
        return self._data.get(collection_id)

    async def save(self, features: CollectionFeatures) -> None:
        self._data[features.collection_id] = features


class FakeChainPort:
    """ChainPort в памяти: данные задаются, вызовы логируются.

    ``verifier`` — опциональная функция sale → SaleVerification для
    кастомных сценариев; иначе результат считается автоматически по
    ``transfers`` (ближайший трансфер с суммой в окне).
    """

    def __init__(
        self,
        *,
        owner: str | None = None,
        transfers: Sequence[NftTransfer] = (),
        wallet: WalletInfo | None = None,
        verifier: Callable[[SaleEvent], SaleVerification] | None = None,
    ) -> None:
        self.owner = owner
        self.transfers: list[NftTransfer] = list(transfers)
        self.wallet = wallet
        self.verifier = verifier
        self.owner_calls: list[str] = []
        self.transfers_calls: list[tuple[str, datetime | None, int]] = []
        self.wallet_calls: list[str] = []
        self.verify_calls: list[Sequence[SaleEvent]] = []

    async def get_nft_owner(self, address: str) -> str | None:
        self.owner_calls.append(address)
        return self.owner

    async def get_nft_transfers(
        self,
        address: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[NftTransfer]:
        self.transfers_calls.append((address, since, limit))
        selected = [
            transfer
            for transfer in self.transfers
            if transfer.nft_address == address and (since is None or transfer.timestamp >= since)
        ]
        return selected[:limit]

    async def get_wallet(self, address: str) -> WalletInfo | None:
        self.wallet_calls.append(address)
        return self.wallet

    async def verify_sale(self, sale: SaleEvent) -> bool:
        return (await self.verify_sales([sale]))[0].matches

    async def verify_sales(self, sales: Sequence[SaleEvent]) -> Sequence[SaleVerification]:
        self.verify_calls.append(sales)
        results: list[SaleVerification] = []
        for sale in sales:
            if self.verifier is not None:
                results.append(self.verifier(sale))
                continue
            candidate = min(
                (
                    t
                    for t in self.transfers
                    if t.nft_address == sale.item_id and t.amount is not None
                ),
                key=lambda t: abs((t.timestamp - sale.sold_at).total_seconds()),
                default=None,
            )
            if candidate is None:
                results.append(
                    SaleVerification(
                        sale_id=sale.id,
                        marketplace_amount=sale.price,
                        matches=False,
                        reason="transfer_not_found",
                    )
                )
                continue
            on_chain = candidate.amount
            assert on_chain is not None
            discrepancy = (
                abs(on_chain.ton - sale.price.ton) / on_chain.ton if not on_chain.is_zero else None
            )
            matches = discrepancy is not None and discrepancy <= Decimal("0.01")
            results.append(
                SaleVerification(
                    sale_id=sale.id,
                    marketplace_amount=sale.price,
                    on_chain_amount=on_chain,
                    discrepancy=discrepancy,
                    matches=matches,
                    reason=None if matches else "price_mismatch",
                )
            )
        return results


class FakeFragmentPort:
    """FragmentPort в памяти: данные задаются, вызовы логируются.

    ``fail`` — эмуляция падения источника: list_auctions поднимает
    FragmentError (для проверки изоляции источника, ТЗ §7).
    """

    def __init__(
        self,
        *,
        assets: Sequence[FragmentAsset] = (),
        auctions: Sequence[FragmentAuction] = (),
        sales: Sequence[SaleEvent] = (),
        fail: bool = False,
    ) -> None:
        self.assets = list(assets)
        self.auctions = list(auctions)
        self.sales = list(sales)
        self.fail = fail
        self.get_asset_calls: list[str] = []
        self.list_assets_calls: list[tuple[str, int]] = []
        self.list_auctions_calls: list[tuple[str, int]] = []
        self.get_sales_calls: list[tuple[str, datetime | None, int]] = []

    async def get_asset(self, address: str) -> FragmentAsset | None:
        self.get_asset_calls.append(address)
        for asset in self.assets:
            if asset.address == address:
                return asset
        return None

    async def list_assets(
        self, collection_address: str, limit: int = 100
    ) -> Sequence[FragmentAsset]:
        self.list_assets_calls.append((collection_address, limit))
        return [asset for asset in self.assets if asset.collection_id == collection_address][:limit]

    async def list_auctions(
        self, collection_address: str, limit: int = 100
    ) -> Sequence[FragmentAuction]:
        self.list_auctions_calls.append((collection_address, limit))
        if self.fail:
            raise FragmentError("fragment.com недоступен")
        return [
            auction
            for auction in self.auctions
            if auction.asset.collection_id == collection_address
        ][:limit]

    async def get_sales(
        self, asset_address: str, since: datetime | None = None, limit: int = 50
    ) -> Sequence[SaleEvent]:
        self.get_sales_calls.append((asset_address, since, limit))
        selected = [
            sale
            for sale in self.sales
            if sale.item_id == asset_address and (since is None or sale.sold_at >= since)
        ]
        return selected[:limit]
