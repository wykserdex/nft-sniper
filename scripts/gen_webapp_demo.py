"""Генерация demo-констант мини-аппа из sample-данных бэкенда.

Демо-режим фронтенда (``/webapp/?demo=1`` или отсутствие бэкенда) использует
встроенные JSON-константы. Чтобы они не расходились с sample-источником,
блок ``demo-constants`` в index.html пересобирается этим скриптом:

    .venv/bin/python scripts/gen_webapp_demo.py
"""

import asyncio
import json
import re
from pathlib import Path

import segno

from nftsniper.contexts.otc.adapters.sample_items import SampleItemSource
from nftsniper.entrypoints.webapp.api import _detail_out
from nftsniper.shared.money import format_ton
from nftsniper.shared.ton_address import TonAddress

HTML = Path(__file__).resolve().parent.parent / (
    "src/nftsniper/entrypoints/webapp/static/index.html"
)
DEMO_ITEM_ID = "anon-888"
DEMO_DEAL_ID = "OTC-DEMO1"
DEMO_BUYER_BYTES = bytes([0x42]) * 32  # синтетический demo-адрес


async def build_block() -> str:
    items = SampleItemSource()
    item = await items.get_item(DEMO_ITEM_ID)
    if item is None:
        msg = f"sample-предмет {DEMO_ITEM_ID} не найден"
        raise RuntimeError(msg)

    detail = _detail_out(item).model_dump()

    seller = item.seller
    amount = item.price_nano
    qr_url = seller.payment_url(amount, DEMO_DEAL_ID)
    payment = {
        "seller_address": seller.user_friendly(bounceable=False),
        "seller_address_short": seller.short,
        "amount_nano": str(amount),
        "amount_ton": format_ton(amount),
        "comment": DEMO_DEAL_ID,
        "qr_url": qr_url,
        "qr_data_uri": segno.make(qr_url, error="m").png_data_uri(scale=10, border=2),
        "tonkeeper_url": seller.tonkeeper_url(amount, DEMO_DEAL_ID),
        "universal_link": seller.universal_link(amount, DEMO_DEAL_ID),
    }
    buyer = TonAddress(workchain=0, raw_bytes=DEMO_BUYER_BYTES).user_friendly(bounceable=False)

    return (
        "const DEMO_ITEM = " + json.dumps(detail, ensure_ascii=False) + ";\n"
        "const DEMO_PAYMENT = "
        + json.dumps(payment, ensure_ascii=False)
        + ";\n"
        + f'const DEMO_BUYER = "{buyer}";'
    )


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    block = asyncio.run(build_block())
    pattern = re.compile(r"// >>> demo-constants.*?// <<< demo-constants", re.DOTALL)
    header = "// >>> demo-constants (генерируется scripts/gen_webapp_demo.py)"
    replacement = f"{header}\n{block}\n// <<< demo-constants"
    if not pattern.search(html):
        msg = "маркеры demo-constants не найдены в index.html"
        raise RuntimeError(msg)
    HTML.write_text(pattern.sub(lambda _: replacement, html, count=1), encoding="utf-8")
    print("webapp demo-constants пересобраны")


if __name__ == "__main__":
    main()
