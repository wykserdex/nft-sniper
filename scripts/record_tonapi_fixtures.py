"""Перезапись фикстур TonAPI с живого API (опционально NFT_TONAPI_KEY).

Схема TonAPI REST v2 версионируется; контрактные тесты гоняются на
записанных фикстурах ``tests/fixtures/tonapi/*.json``. При смене схемы —
обновить фикстуры одной командой:

    NFT_TONAPI_KEY=... python scripts/record_tonapi_fixtures.py \\
        --nft 0:hex... --wallet 0:hex...

Скрипт шлёт те же GET-запросы, что и адаптер (``adapter.py``), и сохраняет
сырые ответы. Затем прогоните контрактные тесты:

    pytest tests/contract/test_tonapi_adapter.py
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tonapi"
ENDPOINT = "https://tonapi.io"


def _get(
    client: httpx.Client, path: str, *, api_key: str, params: dict[str, Any] | None = None
) -> Any:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = client.get(f"{ENDPOINT}{path}", params=params, headers=headers)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nft", required=True, help="адрес NFT (0:hex или UQ...)")
    parser.add_argument("--wallet", required=True, help="адрес кошелька (0:hex или UQ...)")
    args = parser.parse_args()

    api_key = os.environ.get("NFT_TONAPI_KEY", "")

    with httpx.Client(timeout=30) as client:
        fixtures: dict[str, Any] = {
            "nft_item.json": _get(client, f"/v2/nfts/{args.nft}", api_key=api_key),
            "nft_history.json": _get(
                client, f"/v2/nfts/{args.nft}/history", api_key=api_key, params={"limit": 50}
            ),
            "account.json": _get(client, f"/v2/accounts/{args.wallet}", api_key=api_key),
            "account_events_first.json": _get(
                client,
                f"/v2/accounts/{args.wallet}/events",
                api_key=api_key,
                params={"limit": 1, "sort_order": "asc"},
            ),
            "account_events_window.json": _get(
                client,
                f"/v2/accounts/{args.wallet}/events",
                api_key=api_key,
                params={"limit": 100},
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
