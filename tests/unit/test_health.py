"""Health-эндпоинты: /healthz, /readyz, /metrics."""

from fastapi.testclient import TestClient

from nftsniper import __version__
from nftsniper.bootstrap import create_app
from nftsniper.config.settings import Settings


def test_healthz_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_readyz_healthy(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        # lifespan уже прошёл — подменяем проверки фейковыми
        async def ok_check() -> None:
            return None

        app.state.health_checks = [
            ("database", ok_check),
            ("redis", ok_check),
        ]
        response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == {"status": "ok"}
    assert body["checks"]["redis"] == {"status": "ok"}


def test_readyz_degraded_when_db_down(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:

        async def down_check() -> None:
            raise RuntimeError("connection refused")

        async def ok_check() -> None:
            return None

        app.state.health_checks = [
            ("database", down_check),
            ("redis", ok_check),
        ]
        response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"
    assert "connection refused" in body["checks"]["database"]["detail"]
    assert body["checks"]["redis"] == {"status": "ok"}


def test_readyz_without_custom_checks_uses_lifespan_ones(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        # lifespan выставил реальные проверки; дублируем их в пустой список
        app.state.health_checks = []
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {}


def test_metrics_exposes_registry(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.content
    assert b"nft_sniper_alerts_sent_total" in body
    assert b"nft_sniper_uptime_seconds" in body
