"""Sample-источник карточек (пока нет реальных sources).

Данные — намеренно близки к живым (из примера алерта в ТЗ §1),
чтобы мини-апп и API можно было гонять до появления настоящего сборщика.
Адреса продавцов — синтетические (детерминированные), не реальные кошельки.
"""

from nftsniper.contexts.otc.domain.item import (
    ItemSnapshot,
    PricePoint,
    Trait,
    ValuationSnapshot,
)
from nftsniper.shared.ton_address import TonAddress, parse_address

_M = 1_000_000_000  # nanoTON в одном TON


def _seller_888() -> TonAddress:
    return parse_address("EQCIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiJUF")


def _seller_4417() -> TonAddress:
    return parse_address("EQB3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3dxGx")


class SampleItemSource:
    """In-memory ItemSourcePort с двумя предметами Anonymous Numbers."""

    def __init__(self) -> None:
        self._items: dict[str, ItemSnapshot] = {
            "anon-888": ItemSnapshot(
                id="anon-888",
                name="Anonymous Telegram Number #888",
                collection_name="Anonymous Numbers",
                image_url="https://ipfs.io/ipfs/QmSampleAnon888TokenImageUri",
                price_nano=120 * _M,
                price_usd_approx="~$580",
                seller=_seller_888(),
                seller_wallet_age="2 дня",
                floor_ton="195",
                floor_24h_change="-3%",
                median_7d_ton="214",
                sales_7d=18,
                liquidity_per_day="2.4",
                listing_age="11 сек",
                rarity_note="топ 8% по коллекции",
                traits=(
                    Trait(name="Number", value="888", rarity="0.4%"),
                    Trait(name="Pattern", value="Repeater", rarity="3.1%"),
                    Trait(name="Length", value="3 цифры", rarity="12.6%"),
                    Trait(name="Type", value="Anonymous", rarity="—"),
                ),
                valuation=ValuationSnapshot(
                    fair_price_nano=207 * _M,
                    discount_pct="-42%",
                    confidence="0.78",
                    explanation=(
                        "Floor P5: 195 TON, стабилен 7 дней",
                        "Медиана 18 сопоставимых продаж (7d, затухание): 214 TON",
                        "Редкость: топ 8% коллекции — премия заложена в оценку",
                    ),
                ),
                risk_flags=("⚠️ Кошелёк продавца создан 2 дня назад",),
                price_history=(
                    PricePoint(days_ago=7, price_nano=228 * _M),
                    PricePoint(days_ago=6, price_nano=224 * _M),
                    PricePoint(days_ago=5, price_nano=219 * _M),
                    PricePoint(days_ago=4, price_nano=216 * _M),
                    PricePoint(days_ago=3, price_nano=218 * _M),
                    PricePoint(days_ago=2, price_nano=210 * _M),
                    PricePoint(days_ago=1, price_nano=205 * _M),
                    PricePoint(days_ago=0, price_nano=195 * _M),
                ),
            ),
            "anon-4417": ItemSnapshot(
                id="anon-4417",
                name="Anonymous Telegram Number #4417",
                collection_name="Anonymous Numbers",
                image_url="https://ipfs.io/ipfs/QmSampleAnon4417TokenImageUri",
                price_nano=95 * _M,
                price_usd_approx="~$450",
                seller=_seller_4417(),
                seller_wallet_age="4 месяца",
                floor_ton="118",
                floor_24h_change="-1%",
                median_7d_ton="131",
                sales_7d=12,
                liquidity_per_day="1.7",
                listing_age="42 сек",
                rarity_note="топ 21% по коллекции",
                traits=(
                    Trait(name="Number", value="4417", rarity="0.9%"),
                    Trait(name="Pattern", value="Ascending", rarity="7.8%"),
                    Trait(name="Length", value="4 цифры", rarity="31.0%"),
                    Trait(name="Type", value="Anonymous", rarity="—"),
                ),
                valuation=ValuationSnapshot(
                    fair_price_nano=131 * _M,
                    discount_pct="-27%",
                    confidence="0.64",
                    explanation=(
                        "Floor P5: 118 TON",
                        "Медиана 12 сопоставимых продаж (7d): 131 TON",
                        "Ниже уверенность: только 12 продаж за 7 дней",
                    ),
                ),
                risk_flags=(),
                price_history=(
                    PricePoint(days_ago=7, price_nano=124 * _M),
                    PricePoint(days_ago=6, price_nano=122 * _M),
                    PricePoint(days_ago=5, price_nano=121 * _M),
                    PricePoint(days_ago=4, price_nano=119 * _M),
                    PricePoint(days_ago=3, price_nano=118 * _M),
                    PricePoint(days_ago=2, price_nano=118 * _M),
                    PricePoint(days_ago=1, price_nano=117 * _M),
                    PricePoint(days_ago=0, price_nano=118 * _M),
                ),
            ),
        }

    async def get_items(self) -> tuple[ItemSnapshot, ...]:
        return tuple(self._items.values())

    async def get_item(self, item_id: str) -> ItemSnapshot | None:
        return self._items.get(item_id)
