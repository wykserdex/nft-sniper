"""Перезапись фикстур GetGems с живого API (нужен ключ NFT_GETGEMS_API_KEY).

Публичный GraphQL GetGems (``api.getgems.io/graphql``) версионируется и требует
API-ключ официального public-api; контрактные тесты гоняются на
записанных фикстурах ``tests/fixtures/getgems/*.json``. При смене схемы —
обновить фикстуры одной командой:

    NFT_GETGEMS_API_KEY=... \\
    python scripts/record_getgems_fixtures.py --collection EQ... --item EQ...

Скрипт шлёт те же GraphQL-документы, что и адаптер (``queries.py``), и
сохраняет сырые ответы. Затем прогоните контрактные тесты:

    pytest tests/contract
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

from nftsniper.contexts.sources.adapters.getgems.queries import (
    COLLECTION_QUERY,
    ITEM_QUERY,
    LISTINGS_QUERY,
    SALES_QUERY,
)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "getgems"
ENDPOINT = "https://api.getgems.io/graphql"


def _post(
    client: httpx.Client,
    *,
    query: str,
    variables: dict[str, Any],
    operation_name: str,
    api_key: str,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "X-API-KEY": api_key}
    body = {"query": query, "variables": variables, "operationName": operation_name}
    response = client.post(ENDPOINT, json=body, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        msg = f"ожидался JSON-объект от {operation_name}"
        raise RuntimeError(msg)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True, help="адрес коллекции (EQ...)")
    parser.add_argument("--item", required=True, help="адрес предмета (EQ...)")
    args = parser.parse_args()

    api_key = os.environ.get("NFT_GETGEMS_API_KEY")
    if not api_key:
        print("Задайте NFT_GETGEMS_API_KEY (ключ официального public-api GetGems).")
        return 2

    with httpx.Client(timeout=30) as client:
        fixtures: dict[str, dict[str, Any]] = {
            "collection.json": _post(
                client,
                query=COLLECTION_QUERY,
                variables={"address": args.collection},
                operation_name="GetGemsCollection",
                api_key=api_key,
            ),
            "item.json": _post(
                client,
                query=ITEM_QUERY,
                variables={"addresses": [args.item]},
                operation_name="GetGemsItem",
                api_key=api_key,
            ),
            "listings.json": _post(
                client,
                query=LISTINGS_QUERY,
                variables={"address": args.collection, "limit": 100, "offset": 0},
                operation_name="GetGemsListings",
                api_key=api_key,
            ),
            "sales.json": _post(
                client,
                query=SALES_QUERY,
                variables={"collectionAddress": args.collection, "limit": 100, "offset": 0},
                operation_name="GetGemsSales",
                api_key=api_key,
            ),
        }

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, payload in fixtures.items():
        target = FIXTURES / name
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"записано: {target.relative_to(FIXTURES.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
