from __future__ import annotations
import asyncio
import logging
import signal

import perspective
import tornado.web
import tornado.ioloop
from perspective.handlers.tornado import PerspectiveTornadoHandler

from vortex.config.settings import load_settings
from vortex.config.table_config import TransportConfig
from vortex.store.mongo import MongoStore
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.health import HealthHandler
from vortex.connectors.base import BaseConnector
from vortex.connectors.nats import NATSConnector
from vortex.connectors.solace import SolaceConnector
from vortex.connectors.websocket_src import WSSourceConnector


_CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "nats": NATSConnector,
    "solace": SolaceConnector,
    "ws": WSSourceConnector,
}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


def make_tornado_app(psp_server, registry) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/websocket", PerspectiveTornadoHandler, {"perspective_server": psp_server}),
            (r"/health", HealthHandler, {"registry": registry}),
        ],
        websocket_ping_interval=30,
        websocket_ping_timeout=120,
    )


def build_connector(transport: TransportConfig, registry, router) -> BaseConnector | None:
    cls = _CONNECTOR_CLASSES.get(transport.type)
    if cls is None:
        logging.getLogger("vortex.server").error(
            "Unknown transport type '%s' for '%s' — skipping",
            transport.type, transport.name,
        )
        return None
    return cls(transport, registry, router)


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("vortex.server")

    logger.info("Starting VortexServerPython on %s:%d", settings.host, settings.port)

    store = MongoStore(settings.mongo.uri, settings.mongo.database)
    transport_configs = store.load_transport_configs()
    table_configs = store.load_table_configs()
    logger.info(
        "Loaded %d transport(s) and %d table(s) from Mongo",
        len(transport_configs), len(table_configs),
    )

    psp_server = perspective.Server()
    local_client = psp_server.new_local_client()

    registry = TableRegistry(local_client)
    known_transports = {t.name for t in transport_configs}
    for cfg in table_configs:
        if cfg.transport_name not in known_transports:
            logger.warning(
                "Table '%s' references unknown transport '%s' — registering but no data will flow",
                cfg.name, cfg.transport_name,
            )
        registry.register(cfg)

    router = UpdateRouter()

    connectors: list[BaseConnector] = []
    for t in transport_configs:
        if not t.enabled:
            logger.info("Transport '%s' disabled — skipping", t.name)
            continue
        conn = build_connector(t, registry, router)
        if conn is None:
            continue
        try:
            await conn.connect()
            await conn.subscribe_all()
            connectors.append(conn)
        except Exception:
            logger.exception("Transport '%s' failed to start", t.name)

    app = make_tornado_app(psp_server, registry)
    server = app.listen(settings.port, settings.host)
    logger.info("Perspective WebSocket endpoint: ws://%s:%d/websocket", settings.host, settings.port)
    logger.info("Health endpoint:                http://%s:%d/health", settings.host, settings.port)

    stop_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM — fall back to default
            signal.signal(sig, lambda *_: _handle_signal())

    await stop_event.wait()

    logger.info("Shutting down connectors...")
    for conn in connectors:
        try:
            await conn.disconnect()
        except Exception:
            logger.exception("Error disconnecting '%s'", conn.name)

    server.stop()
    store.close()
    logger.info("VortexServerPython stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
