"""Перезапись фикстур Fragment с живых источников (опционально NFT_TONAPI_KEY).

Контрактные тесты гоняются на записанных фикстурах:
``tests/fixtures/fragment/*.html`` (публичные страницы fragment.com) и
``tests/fixtures/tonapi/fragment_*.json`` (TonAPI REST v2). При смене вёрстки
или схемы — обновить одной командой:

    NFT_TONAPI_KEY=... python scripts/record_fragment_fixtures.py \\
        --usernames 0:hex... --numbers 0:hex...

Скрипт делает те же GET/POST, что и адаптер: список предметов коллекции,
bulk-метаданные, а также HTML-страницы ``/`` и ``/numbers``. Частота запросов
к fragment.com ограничена (1 запрос), ключ TonAPI не обязателен.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
FRAG = FIXTURES / "fragment"
TON = FIXTURES / "tonapi"
TONAPI = "https://tonapi.io"
FRAGMENT = "https://fragment.com"
USER_AGENT = "nft-sniper/0.1 (fixture recorder)"


def _tonapi_get(
    client: httpx.Client, path: str, *, api_key: str, params: dict[str, Any] | None = None
) -> Any:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = client.get(f"{TONAPI}{path}", params=params, headers=headers)
    response.raise_for_status()
    return response.json()


def _tonapi_post(client: httpx.Client, path: str, *, api_key: str, body: dict[str, Any]) -> Any:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = client.post(f"{TONAPI}{path}", json=body, headers=headers)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usernames", required=True, help="адрес коллекции юзернеймов (0:hex)")
    parser.add_argument("--numbers", required=True, help="адрес коллекции номеров (0:hex)")
    args = parser.parse_args()

    api_key = os.environ.get("NFT_TONAPI_KEY", "")

    FRAG.mkdir(parents=True, exist_ok=True)
    TON.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        # ── fragment.com: публичный HTML ──────────────────────────────
        for path, name in (("/", "usernames.html"), ("/numbers", "numbers.html")):
            response = client.get(f"{FRAGMENT}{path}")
            response.raise_for_status()
            (FRAG / name).write_text(response.text, encoding="utf-8")
            print(f"записано: tests/fixtures/fragment/{name}")

        # ── TonAPI: список предметов + bulk-метаданные ─────────────────
        for collection, prefix in (
            (args.usernames, "fragment_usernames"),
            (args.numbers, "fragment_numbers"),
        ):
            items = _tonapi_get(
                client,
                f"/v2/nfts/collections/{collection}/items",
                api_key=api_key,
                params={"limit": 100},
            )
            (TON / f"{prefix}_items.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            addresses = [
                item["address"]
                for item in items.get("nft_items", [])
                if isinstance(item, dict) and isinstance(item.get("address"), str)
            ]
            bulk = _tonapi_post(
                client,
                "/v2/nfts/_bulk",
                api_key=api_key,
                body={"account_ids": addresses[:100]},
            )
            (TON / f"{prefix}_bulk.json").write_text(
                json.dumps(bulk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"записано: tests/fixtures/tonapi/{prefix}_items.json, {prefix}_bulk.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
