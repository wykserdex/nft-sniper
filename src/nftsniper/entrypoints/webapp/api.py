"""API мини-аппа (префикс /api/webapp)."""

from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from nftsniper.config.settings import Settings
from nftsniper.contexts.otc.adapters.dev_transfers import DevTransferStore
from nftsniper.contexts.otc.application.service import OtcService, PaymentPayload
from nftsniper.contexts.otc.domain.deal import ItemNotFoundError, OtcDeal, OtcNotFoundError
from nftsniper.contexts.otc.domain.item import ItemSnapshot
from nftsniper.shared.money import format_ton
from nftsniper.shared.ton_address import TonAddressError

from . import schemas

WEBAPP_STATIC = Path(__file__).parent / "static"


def _detail_out(item: ItemSnapshot) -> schemas.NftDetailOut:
    return schemas.NftDetailOut(
        id=item.id,
        name=item.name,
        collection_name=item.collection_name,
        image_url=item.image_url,
        price_ton=format_ton(item.price_nano),
        price_nano=str(item.price_nano),
        price_usd_approx=item.price_usd_approx,
        floor_ton=item.floor_ton,
        floor_24h_change=item.floor_24h_change,
        median_7d_ton=item.median_7d_ton,
        sales_7d=item.sales_7d,
        liquidity_per_day=item.liquidity_per_day,
        listing_age=item.listing_age,
        rarity_note=item.rarity_note,
        traits=[schemas.TraitOut(name=t.name, value=t.value, rarity=t.rarity) for t in item.traits],
        valuation=schemas.ValuationOut(
            fair_price_ton=format_ton(item.valuation.fair_price_nano),
            discount_pct=item.valuation.discount_pct,
            confidence=item.valuation.confidence,
            explanation=list(item.valuation.explanation),
        ),
        risk_flags=list(item.risk_flags),
        seller_address=item.seller.user_friendly(bounceable=False),
        seller_address_short=item.seller.short,
        seller_wallet_age=item.seller_wallet_age,
        price_history=[
            schemas.PricePointOut(days_ago=p.days_ago, price_ton=format_ton(p.price_nano))
            for p in item.price_history
        ],
    )


def _payment_out(payload: PaymentPayload) -> schemas.PaymentOut:
    return schemas.PaymentOut(
        seller_address=payload.seller_address,
        seller_address_short=payload.seller_address_short,
        amount_nano=payload.amount_nano,
        amount_ton=payload.amount_ton,
        comment=payload.comment,
        qr_url=payload.qr_url,
        qr_data_uri=payload.qr_data_uri,
        tonkeeper_url=payload.tonkeeper_url,
        universal_link=payload.universal_link,
    )


def _status_out(deal: OtcDeal) -> schemas.OtcStatusOut:
    return schemas.OtcStatusOut(
        deal_id=deal.id,
        status=deal.status.value,
        amount_ton=format_ton(deal.amount_nano),
        seller_address=deal.seller.user_friendly(bounceable=False),
        paid_tx_hash=deal.paid_tx_hash,
        nft_tx_hash=deal.nft_tx_hash,
        paid_tonscan_url=(
            f"https://tonscan.org/tx/{deal.paid_tx_hash}" if deal.paid_tx_hash else None
        ),
        nft_tonscan_url=(
            f"https://tonscan.org/tx/{deal.nft_tx_hash}" if deal.nft_tx_hash else None
        ),
    )


def build_webapp_router(
    *,
    settings: Settings,
    service: OtcService,
    dev_transfers: DevTransferStore | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/webapp", tags=["webapp"])

    @router.get("/items", response_model=list[schemas.ItemBriefOut])
    async def list_items() -> list[schemas.ItemBriefOut]:
        items = await service.list_items()
        return [schemas.ItemBriefOut(**asdict(v)) for v in items]

    @router.get("/nft/{item_id}", response_model=schemas.NftDetailOut)
    async def get_nft(item_id: str) -> schemas.NftDetailOut:
        try:
            return _detail_out(await service.get_item(item_id))
        except ItemNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"предмет не найден: {item_id}") from exc

    @router.post("/otc/create", response_model=schemas.OtcCreateOut, status_code=201)
    async def create_otc(body: schemas.OtcCreateIn) -> schemas.OtcCreateOut:
        try:
            deal = await service.create_deal(body.item_id, body.buyer_address)
        except ItemNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=f"предмет не найден: {body.item_id}"
            ) from exc
        except TonAddressError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = service.payload(deal)
        return schemas.OtcCreateOut(
            deal_id=deal.id,
            status=deal.status.value,
            expires_in_sec=int((deal.expires_at - deal.created_at).total_seconds()),
            payment=_payment_out(payload),
        )

    @router.get("/otc/{deal_id}", response_model=schemas.OtcStatusOut)
    async def otc_status(deal_id: str) -> schemas.OtcStatusOut:
        try:
            return _status_out(await service.get_deal(deal_id))
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc

    @router.get("/otc/{deal_id}/payment", response_model=schemas.PaymentOut)
    async def otc_payment(deal_id: str) -> schemas.PaymentOut:
        try:
            deal = await service.get_deal(deal_id)
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc
        return _payment_out(service.payload(deal))

    @router.post("/otc/{deal_id}/check-payment", response_model=schemas.OtcStatusOut)
    async def otc_check_payment(deal_id: str) -> schemas.OtcStatusOut:
        try:
            return _status_out(await service.check_payment(deal_id))
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc

    @router.post("/otc/{deal_id}/cancel", response_model=schemas.OtcStatusOut)
    async def otc_cancel(deal_id: str) -> schemas.OtcStatusOut:
        try:
            return _status_out(await service.cancel_deal(deal_id))
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc

    @router.post("/otc/{deal_id}/confirm-nft", response_model=schemas.OtcStatusOut)
    async def otc_confirm_nft(deal_id: str, body: schemas.ConfirmNftIn) -> schemas.OtcStatusOut:
        try:
            return _status_out(await service.confirm_nft_received(deal_id, body.tx_hash))
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc

    @router.get("/otc/{deal_id}/qr")
    async def otc_qr(deal_id: str) -> Response:
        try:
            deal = await service.get_deal(deal_id)
        except OtcNotFoundError as exc:
            raise HTTPException(status_code=404, detail="сделка не найдена") from exc
        payload = service.payload(deal)
        png = base64.b64decode(payload.qr_data_uri.split(",", 1)[1])
        return Response(content=png, media_type="image/png")

    # Dev-only: симуляция on-chain пересылки (пока нет ChainPort).
    # В прод dev_transfers is None — роут не существует.
    if dev_transfers is not None:

        @router.post("/dev/transfer", status_code=201)
        async def dev_transfer(body: schemas.DevTransferIn) -> dict[str, str]:
            transfer = await dev_transfers.simulate(
                from_address=body.from_address,
                to_address=body.to_address,
                amount_nano=body.amount_nano,
                comment=body.comment,
                at=datetime.now(UTC),
            )
            return {"tx_hash": transfer.tx_hash}

    return router
