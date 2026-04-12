from __future__ import annotations
import asyncio
import signal
import sys
import time

import perspective
import tornado.web
from perspective.handlers.tornado import PerspectiveTornadoHandler

from vortex.config.settings import load_settings
from vortex.config.table_config import TransportConfig
from vortex.store.mongo import MongoStore
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.health import LivenessHandler, ReadinessHandler, MetricsHandler
from vortex.status import StatusHandler
from vortex.connectors.base import BaseConnector
from vortex.connectors.nats import NATSConnector
from vortex.connectors.solace import SolaceConnector
from vortex.connectors.websocket_src import WSSourceConnector
from vortex.observability import (
    configure_logging,
    get_logger,
    new_correlation_id,
    metrics,
)


_CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "nats": NATSConnector,
    "solace": SolaceConnector,
    "ws": WSSourceConnector,
}

VERSION = "0.1.0"

logger = get_logger("vortex.server")


def _resolve_log_format(setting: str, level: str) -> bool:
    """Translate log_format setting → json_output bool for configure_logging."""
    s = (setting or "auto").lower()
    if s == "json":
        return True
    if s == "console":
        return False
    # auto: console for DEBUG, json otherwise
    return level.upper() != "DEBUG"


def make_tornado_app(psp_server, registry, store, connectors, shutdown_flag, start_time) -> tornado.web.Application:
    health_kwargs = {
        "registry": registry,
        "store": store,
        "connectors": connectors,
        "shutdown_flag": shutdown_flag,
    }
    status_kwargs = {
        "registry": registry,
        "store": store,
        "connectors": connectors,
        "start_time": start_time,
        "version": VERSION,
        "shutdown_flag": shutdown_flag,
    }
    return tornado.web.Application(
        [
            (r"/websocket", PerspectiveTornadoHandler, {"perspective_server": psp_server}),
            (r"/health/live", LivenessHandler, health_kwargs),
            (r"/health/ready", ReadinessHandler, health_kwargs),
            # Backwards-compatible alias for the old /health endpoint
            (r"/health", ReadinessHandler, health_kwargs),
            (r"/metrics", MetricsHandler),
            (r"/api/status", StatusHandler, status_kwargs),
        ],
        websocket_ping_interval=30,
        websocket_ping_timeout=120,
    )


def build_connector(transport: TransportConfig, registry, router) -> BaseConnector | None:
    cls = _CONNECTOR_CLASSES.get(transport.type)
    if cls is None:
        logger.error(
            "transport.unknown_type",
            transport=transport.name,
            type=transport.type,
        )
        return None
    return cls(transport, registry, router)


async def main() -> None:
    settings = load_settings()
    json_output = _resolve_log_format(settings.log_format, settings.log_level)
    configure_logging(level=settings.log_level, json_output=json_output)

    new_correlation_id()
    metrics.SERVER_INFO.labels(version=VERSION).set(1)
    metrics.SHUTTING_DOWN.set(0)
    start_time = time.monotonic()

    logger.info(
        "server.starting",
        version=VERSION,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_format="json" if json_output else "console",
    )

    # ── Mongo ───────────────────────────────────────────────────────────────
    try:
        store = MongoStore(settings.mongo.uri, settings.mongo.database)
        store._client.admin.command("ping")
        metrics.MONGO_REACHABLE.set(1)
    except Exception:
        metrics.MONGO_REACHABLE.set(0)
        logger.exception("server.mongo_unavailable", uri=settings.mongo.uri)
        raise

    transport_configs = store.load_transport_configs()
    table_configs = store.load_table_configs()
    logger.info(
        "server.config_loaded",
        transports=len(transport_configs),
        tables=len(table_configs),
    )

    # ── Perspective engine ──────────────────────────────────────────────────
    psp_server = perspective.Server()
    local_client = psp_server.new_local_client()

    registry = TableRegistry(local_client)
    known_transports = {t.name for t in transport_configs}
    for cfg in table_configs:
        if cfg.transport_name not in known_transports:
            logger.warning(
                "table.unknown_transport",
                table=cfg.name,
                transport=cfg.transport_name,
            )
        registry.register(cfg)

    router = UpdateRouter()

    # ── Connectors ──────────────────────────────────────────────────────────
    connectors: list[BaseConnector] = []
    for t in transport_configs:
        if not t.enabled:
            logger.info("transport.disabled", transport=t.name, type=t.type)
            continue
        conn = build_connector(t, registry, router)
        if conn is None:
            continue
        connectors.append(conn)

    # Start supervisors. Each handles its own connect retries; we never
    # block here on broker availability — that lets the readiness check
    # surface the actual state instead of failing startup outright.
    for conn in connectors:
        await conn.start()

    # ── Tornado ─────────────────────────────────────────────────────────────
    shutdown_flag = asyncio.Event()
    app = make_tornado_app(psp_server, registry, store, connectors, shutdown_flag, start_time)
    server = app.listen(settings.port, settings.host)
    logger.info(
        "server.listening",
        websocket=f"ws://{settings.host}:{settings.port}/websocket",
        live=f"http://{settings.host}:{settings.port}/health/live",
        ready=f"http://{settings.host}:{settings.port}/health/ready",
        metrics_endpoint=f"http://{settings.host}:{settings.port}/metrics",
        status=f"http://{settings.host}:{settings.port}/api/status",
    )

    # ── Signals ─────────────────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _signal_received():
        if not stop_event.is_set():
            logger.info("server.signal_received")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_received)
        except NotImplementedError:
            # Windows: add_signal_handler not supported for SIGTERM in some setups
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_signal_received))

    await stop_event.wait()

    # ── Graceful shutdown — bounded ─────────────────────────────────────────
    metrics.SHUTTING_DOWN.set(1)
    shutdown_flag.set()
    logger.info("server.shutdown_started", timeout=settings.shutdown_timeout)

    try:
        await asyncio.wait_for(
            _drain_and_close(server, connectors, store, settings.shutdown_timeout),
            timeout=settings.shutdown_timeout + 5.0,
        )
    except asyncio.TimeoutError:
        logger.error("server.shutdown_hard_timeout")

    logger.info("server.shutdown_complete")


async def _drain_and_close(
    server,
    connectors: list[BaseConnector],
    store: MongoStore,
    per_connector_timeout: float,
) -> None:
    # Stop accepting new connections immediately
    server.stop()
    logger.info("server.tcp_listener_stopped")

    # Stop connectors in parallel — each bounded by per_connector_timeout
    if connectors:
        results = await asyncio.gather(
            *(c.stop(timeout=per_connector_timeout) for c in connectors),
            return_exceptions=True,
        )
        for c, r in zip(connectors, results):
            if isinstance(r, Exception):
                logger.error(
                    "server.connector_stop_error",
                    transport=c.name,
                    error=str(r),
                    error_type=r.__class__.__name__,
                )

    try:
        store.close()
        logger.info("server.mongo_closed")
    except Exception:
        logger.exception("server.mongo_close_error")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    run()
