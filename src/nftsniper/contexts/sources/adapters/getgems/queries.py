"""GraphQL-документы GetGems (закреплённый контракт, версия 1).

Про публичный API GetGems:
- исторический эндпоинт ``api.getgems.io/graphql`` теперь требует API-ключ и
  отсылает к официальному ``https://getgems.io/public-api`` и ``https://tonapi.io/``;
- поэтому контракт ниже закрепляется записанными фикстурами
  ``tests/fixtures/getgems/*.json`` и перезаписывается одной командой
  ``scripts/record_getgems_fixtures.py`` при смене схемы.

Поля продажи читаются защитно (см. ``normalizer.py``): ``fullPrice`` / ``price`` /
``maxBid`` / ``minBid``, ``timestamp`` / ``createdAt`` — чтобы пережить мелкие
изменения схемы без падения всего конвейера.
"""

GETGEMS_SALE_FRAGMENT = (
    "fragment GetGemsSale on NftSale {\n"
    "  __typename\n"
    "  address\n"
    "  createdAt\n"
    "  endsAt\n"
    "  owner\n"
    "  marketplace\n"
    "  price\n"
    "  ... on NftSaleSimple {\n"
    "    fullPrice\n"
    "  }\n"
    "  ... on NftSaleOffer {\n"
    "    fullPrice\n"
    "  }\n"
    "  ... on NftSaleAuction {\n"
    "    minBid\n"
    "    maxBid\n"
    "    status\n"
    "  }\n"
    "}\n"
)

_ITEM_FIELDS = (
    "  address\n"
    "  index\n"
    "  name\n"
    "  collectionAddress\n"
    "  ownerAddress\n"
    "  attributes {\n"
    "    traitType\n"
    "    value\n"
    "  }\n"
    "  sale {\n"
    "    ...GetGemsSale\n"
    "  }\n"
)

COLLECTION_QUERY = (
    "query GetGemsCollection($address: String!) {\n"
    "  nftCollectionByAddress(address: $address) {\n"
    "    address\n"
    "    ownerAddress\n"
    "    nextItemIndex\n"
    "    verified\n"
    "    meta {\n"
    "      name\n"
    "    }\n"
    "  }\n"
    "}\n"
)

ITEM_QUERY = (
    "query GetGemsItem($addresses: [String!]!) {\n"
    "  nftItemsByAddresses(addresses: $addresses) {\n" + _ITEM_FIELDS + "  }\n"
    "}\n" + GETGEMS_SALE_FRAGMENT
)

LISTINGS_QUERY = (
    "query GetGemsListings($address: String!, $limit: Int, $offset: Int) {\n"
    "  getNftItemsByCollectionOnSale(address: $address, limit: $limit, offset: $offset, "
    'sort: "price", order: "asc") {\n'
    "    items {\n" + _ITEM_FIELDS + "    }\n"
    "    cursor\n"
    "  }\n"
    "}\n" + GETGEMS_SALE_FRAGMENT
)

SALES_QUERY = (
    "query GetGemsSales($collectionAddress: String!, $limit: Int, $offset: Int) {\n"
    "  nftSalesOnCollection(collectionAddress: $collectionAddress, "
    "limit: $limit, offset: $offset) {\n"
    "    __typename\n"
    "    txHash\n"
    "    timestamp\n"
    "    price\n"
    "    buyer\n"
    "    seller\n"
    "    nft {\n"
    "      address\n"
    "      collectionAddress\n"
    "    }\n"
    "  }\n"
    "}\n"
)

OPERATION_NAMES = ("GetGemsCollection", "GetGemsItem", "GetGemsListings", "GetGemsSales")
