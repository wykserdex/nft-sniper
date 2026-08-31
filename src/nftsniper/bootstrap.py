"""Сборка приложения: FastAPI-приложение с health-эндпоинтами.

- ``GET /healthz`` — живость процесса (liveness), всегда 200.
- ``GET /readyz``  — готовность: проверки инфраструктурных компонентов
  (Postgres, Redis). 503, если что-то недоступно.
- ``GET /metrics`` — Prometheus-снимок метрик.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from nftsniper import __version__
from nftsniper.config.settings import Settings, get_settings
from nftsniper.entrypoints.webapp.api import build_webapp_router
from nftsniper.entrypoints.webapp.wiring import create_webapp_deps
from nftsniper.infrastructure.cache.redis import create_redis, ping_redis
from nftsniper.infrastructure.database.engine import create_database, ping_db
from nftsniper.observability import metrics
from nftsniper.observability.logging import get_logger

logger = get_logger(__name__)

HealthCheck = Callable[[], Awaitable[None]]


async def _run_check_async(check: HealthCheck) -> dict[str, str]:
    try:
        await check()
        return {"status": "ok"}
    except Exception as exc:
        # Статус готовности не зависит от типа ошибки: пишем имя класса + текст.
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собирает FastAPI-приложение. Настройки — из env, если не переданы явно."""
    effective_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = create_database(effective_settings)
        redis_pool = create_redis(effective_settings)
        app.state.settings = effective_settings
        app.state.database = database
        app.state.redis = redis_pool
        app.state.health_checks = [
            ("database", lambda: ping_db(database)),
            ("redis", lambda: ping_redis(redis_pool)),
        ]
        logger.info("app_started", version=__version__, env=effective_settings.app_env)
        try:
            yield
        finally:
            await redis_pool.aclose()
            await database.dispose()
            logger.info("app_stopped")

    app = FastAPI(title="nft-sniper", version=__version__, lifespan=lifespan)
    app.state.settings = effective_settings

    # Mini App (правки к ТЗ, §11): деталка NFT + OTC-оплата в TON Keeper
    webapp_deps = create_webapp_deps(effective_settings)
    app.include_router(
        build_webapp_router(
            settings=effective_settings,
            service=webapp_deps.service,
            dev_transfers=webapp_deps.dev_transfers,
        )
    )
    app.mount(
        "/webapp",
        StaticFiles(directory=webapp_deps.static_dir, html=True),
        name="webapp",
    )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        checks: list[tuple[str, HealthCheck]] = getattr(request.app.state, "health_checks", [])
        results: dict[str, dict[str, str]] = {}
        for name, check in checks:
            results[name] = await _run_check_async(check)
        healthy = all(item["status"] == "ok" for item in results.values())
        body = {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "checks": results,
        }
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        return Response(metrics.render_metrics(), media_type=metrics.CONTENT_TYPE)

    return app
