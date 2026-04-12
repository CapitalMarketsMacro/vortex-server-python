from __future__ import annotations
import asyncio
import nats

from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.observability import get_logger

logger = get_logger(__name__)


class NATSConnector(BaseConnector):
    def __init__(self, transport, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._nc = None
        self._js = None
        self._disconnect_event = asyncio.Event()

    async def _do_connect(self) -> None:
        cfg = self.transport.config

        async def _on_disconnected():
            logger.warning("nats.disconnected")
            self._connected.clear()
            self._disconnect_event.set()

        async def _on_reconnected():
            logger.info("nats.reconnected")
            self._connected.set()
            self._disconnect_event.clear()

        async def _on_error(e):
            logger.error("nats.error", error=str(e), error_type=e.__class__.__name__)

        async def _on_closed():
            logger.warning("nats.closed")
            self._disconnect_event.set()

        connect_kwargs: dict = {
            "servers": cfg.get("url", "nats://localhost:4222"),
            "name": f"vortex-{self.name}",
            "max_reconnect_attempts": -1,           # infinite — internal reconnect
            "reconnect_time_wait": 2.0,
            "ping_interval": 20,
            "max_outstanding_pings": 5,
            "disconnected_cb": _on_disconnected,
            "reconnected_cb": _on_reconnected,
            "error_cb": _on_error,
            "closed_cb": _on_closed,
        }
        if cfg.get("user"):
            connect_kwargs["user"] = cfg["user"]
            connect_kwargs["password"] = cfg.get("password")
        if cfg.get("token"):
            connect_kwargs["token"] = cfg["token"]

        self._disconnect_event.clear()
        self._nc = await nats.connect(**connect_kwargs)
        self._js = self._nc.jetstream()
        logger.info("nats.connected", url=connect_kwargs["servers"])

    async def _do_subscribe(self) -> None:
        configs: list[TableConfig] = self.registry.tables_by_transport(self.name)
        if not configs:
            logger.info("nats.no_tables", transport=self.name)
            return
        for cfg in configs:
            await self._subscribe_one(cfg)

    async def _subscribe_one(self, cfg: TableConfig) -> None:
        table_name = cfg.name
        is_jetstream = cfg.nats_mode == "jetstream"

        async def handler(msg):
            await self._dispatch(table_name, msg.data)
            if is_jetstream:
                try:
                    await msg.ack()
                except Exception:
                    logger.exception("nats.ack_failed", table=table_name)

        if is_jetstream:
            try:
                kwargs: dict = {
                    "cb": handler,
                    "deliver_policy": nats.js.api.DeliverPolicy.NEW,
                }
                if cfg.durable:
                    kwargs["durable"] = cfg.durable
                await self._js.subscribe(cfg.topic, **kwargs)
                logger.info(
                    "nats.subscribed",
                    mode="jetstream",
                    subject=cfg.topic,
                    table=table_name,
                    durable=cfg.durable or "<ephemeral>",
                )
            except Exception as e:
                logger.error(
                    "nats.subscribe_failed",
                    mode="jetstream",
                    subject=cfg.topic,
                    table=table_name,
                    durable=cfg.durable,
                    error=str(e),
                    error_type=e.__class__.__name__,
                    hint="No JetStream stream covers this subject. "
                         "Create one or set nats_mode='core'.",
                )
        else:
            await self._nc.subscribe(cfg.topic, cb=handler)
            logger.info(
                "nats.subscribed",
                mode="core",
                subject=cfg.topic,
                table=table_name,
            )

    async def _wait_until_done(self) -> None:
        """
        Wake up if the underlying NATS client closes (after exhausting its
        own reconnect attempts) or if shutdown is requested.
        """
        stop_task = asyncio.create_task(self._stopping.wait(), name=f"{self.name}-stop")
        disc_task = asyncio.create_task(self._disconnect_event.wait(), name=f"{self.name}-disc")
        try:
            done, pending = await asyncio.wait(
                {stop_task, disc_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if stop_task in done:
                return
            raise ConnectionError("nats client closed")
        finally:
            for t in (stop_task, disc_task):
                if not t.done():
                    t.cancel()

    async def _do_disconnect(self) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.drain()
        except Exception:
            try:
                await self._nc.close()
            except Exception:
                pass
        finally:
            self._nc = None
            self._js = None
            logger.info("nats.disconnected_clean")
