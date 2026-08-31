"""CLI nft-sniper.

Команды:
- ``serve``   — HTTP-сервер с health-эндпоинтами (liveness/readiness/metrics);
- ``check``   — проверка связности с Postgres и Redis (exit 0/1);
- ``worker``  — конвейер poll → score → risk → notify (по расписанию);
- ``version`` — версия пакета.
"""

import argparse
import asyncio
import sys

import uvicorn

from nftsniper import __version__
from nftsniper.bootstrap import create_app
from nftsniper.config.settings import Settings, get_settings
from nftsniper.entrypoints.bot.main import run_bot
from nftsniper.entrypoints.workers.pipeline import PipelineReport
from nftsniper.entrypoints.workers.runner import run_pipeline_loop
from nftsniper.entrypoints.workers.wiring import build_worker
from nftsniper.infrastructure.cache.redis import create_redis, ping_redis
from nftsniper.infrastructure.database.engine import create_database, ping_db
from nftsniper.observability.logging import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nftsniper",
        description="NFT Sniper: поиск недооценённых NFT на TON (решение за человеком)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="HTTP-сервер (health-эндпоинты)")
    serve.add_argument("--host", default=None, help="по умолчанию из NFT_HTTP_HOST")
    serve.add_argument("--port", type=int, default=None, help="по умолчанию из NFT_HTTP_PORT")
    serve.add_argument(
        "--log-json", action="store_true", help="форсировать JSON-логи независимо от env"
    )

    subparsers.add_parser("check", help="проверка связности с Postgres и Redis")
    subparsers.add_parser("version", help="печать версии")
    bot = subparsers.add_parser("bot", help="Telegram-бот (long polling)")
    bot.add_argument(
        "--log-json", action="store_true", help="форсировать JSON-логи независимо от env"
    )
    worker = subparsers.add_parser(
        "worker", help="конвейер poll → score → risk → notify (по расписанию)"
    )
    worker.add_argument("--collection", required=True, help="on-chain-адрес коллекции для опроса")
    worker.add_argument("--once", action="store_true", help="один цикл вместо бесконечного")
    worker.add_argument(
        "--interval", type=int, default=3, help="интервал опроса, сек (по умолчанию 3)"
    )
    worker.add_argument(
        "--log-json", action="store_true", help="форсировать JSON-логи независимо от env"
    )
    return parser


async def _run_worker(settings: Settings, *, collection: str, once: bool, interval: int) -> None:
    """Конвейер: один цикл (--once) или бесконечный (по умолчанию)."""
    components = build_worker(settings)

    async def poll() -> PipelineReport:
        return await components.pipeline.run(collection)

    if once:
        await run_pipeline_loop(poll, cycles=1, poll_interval_seconds=0)
    else:
        await run_pipeline_loop(poll, poll_interval_seconds=interval)


async def _run_check() -> int:
    settings = get_settings()
    exit_code = 0

    database = create_database(settings)
    try:
        await ping_db(database)
        print("database: ok")
    except Exception as exc:
        print(f"database: error ({type(exc).__name__}: {exc})")
        exit_code = 1
    finally:
        await database.dispose()

    pool = create_redis(settings)
    try:
        await ping_redis(pool)
        print("redis: ok")
    except Exception as exc:
        print(f"redis: error ({type(exc).__name__}: {exc})")
        exit_code = 1
    finally:
        await pool.aclose()

    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "check":
        setup_logging(settings.log_level, settings.log_json)
        return asyncio.run(_run_check())

    if args.command == "bot":
        setup_logging(settings.log_level, settings.log_json or args.log_json)
        asyncio.run(run_bot(settings))
        return 0

    if args.command == "worker":
        setup_logging(settings.log_level, settings.log_json or args.log_json)
        asyncio.run(
            _run_worker(
                settings,
                collection=args.collection,
                once=args.once,
                interval=args.interval,
            )
        )
        return 0

    host = args.host if args.host is not None else settings.http_host
    port = args.port if args.port is not None else settings.http_port
    setup_logging(settings.log_level, settings.log_json or args.log_json)

    app = create_app(settings)
    # log_config=None: uvicorn пишет через наш structlog-конвейер
    uvicorn.run(app, host=host, port=port, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
