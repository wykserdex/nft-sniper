"""API мини-аппа: деталка, OTC-цикл, dev-пересылки, QR, статика."""

from fastapi.testclient import TestClient

from nftsniper.bootstrap import create_app
from nftsniper.config.settings import Settings
from nftsniper.shared.ton_address import TonAddress

BUYER = TonAddress(workchain=0, raw_bytes=bytes([0x42]) * 32).user_friendly(bounceable=False)


def test_items_list(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/webapp/items")
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == ["anon-888", "anon-4417"]
    assert body[0]["price_ton"] == "120"


def test_nft_detail(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/webapp/nft/anon-888")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Anonymous Telegram Number #888"
    assert body["price_ton"] == "120"
    assert body["valuation"]["fair_price_ton"] == "207"
    assert body["valuation"]["confidence"] == "0.78"
    assert len(body["price_history"]) == 8
    assert body["risk_flags"]
    assert body["seller_address"].startswith("UQ")


def test_nft_detail_404(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/webapp/nft/nope")
    assert response.status_code == 404


def test_full_otc_flow(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/webapp/otc/create",
            json={"item_id": "anon-888", "buyer_address": BUYER},
        )
        assert created.status_code == 201
        deal = created.json()
        assert deal["deal_id"].startswith("OTC-")
        assert deal["expires_in_sec"] == 1800
        payment = deal["payment"]
        assert payment["amount_ton"] == "120"
        assert payment["qr_data_uri"].startswith("data:image/png;base64,")
        assert payment["tonkeeper_url"].startswith("tonkeeper://transfer/")
        assert payment["universal_link"].startswith("https://app.tonkeeper.com/transfer/")

        dev = client.post(
            "/api/webapp/dev/transfer",
            json={
                "from_address": BUYER,
                "to_address": payment["seller_address"],
                "amount_nano": int(payment["amount_nano"]),
                "comment": payment["comment"],
            },
        )
        assert dev.status_code == 201
        assert dev.json()["tx_hash"].startswith("dev_tx_")

        status = client.post(f"/api/webapp/otc/{deal['deal_id']}/check-payment").json()
        assert status["status"] == "paid"
        assert status["paid_tx_hash"].startswith("dev_tx_")

        final = client.post(f"/api/webapp/otc/{deal['deal_id']}/confirm-nft", json={}).json()
        assert final["status"] == "completed"

        qr = client.get(f"/api/webapp/otc/{deal['deal_id']}/qr")
        assert qr.status_code == 200
        assert qr.headers["content-type"] == "image/png"
        assert qr.content[:4] == b"\x89PNG"


def test_create_with_bad_address_422(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/webapp/otc/create",
            json={"item_id": "anon-888", "buyer_address": "not-an-address"},
        )
    assert response.status_code == 422
    assert "адрес" in response.json()["detail"]


def test_dev_transfer_forbidden_in_prod() -> None:
    prod = Settings(_env_file=None, app_env="prod")
    with TestClient(create_app(prod)) as client:
        response = client.post(
            "/api/webapp/dev/transfer",
            json={
                "from_address": BUYER,
                "to_address": BUYER,
                "amount_nano": 1,
                "comment": "x",
            },
        )
    assert response.status_code == 404


def test_webapp_static_served(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/webapp/")
    assert response.status_code == 200
    assert "NFT" in response.text
    assert "Sniper" in response.text
