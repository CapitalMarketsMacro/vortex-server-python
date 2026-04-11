from __future__ import annotations
import logging
import nats
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig, TransportConfig

logger = logging.getLogger(__name__)


class NATSConnector(BaseConnector):
    def __init__(self, transport: TransportConfig, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._nc = None
        self._js = None

    async def connect(self) -> None:
        cfg = self.transport.config
        connect_kwargs: dict = {"servers": cfg.get("url", "nats://localhost:4222")}
        if cfg.get("user"):
            connect_kwargs["user"] = cfg["user"]
            connect_kwargs["password"] = cfg.get("password")
        if cfg.get("token"):
            connect_kwargs["token"] = cfg["token"]

        self._nc = await nats.connect(**connect_kwargs)
        self._js = self._nc.jetstream()
        self._connected = True
        logger.info("[%s] NATSConnector: connected to %s", self.name, connect_kwargs["servers"])

    async def subscribe_all(self) -> None:
        configs: list[TableConfig] = self.registry.tables_by_transport(self.name)
        for cfg in configs:
            await self._subscribe_one(cfg)

    async def _subscribe_one(self, cfg: TableConfig) -> None:
        table_name = cfg.name
        is_jetstream = cfg.nats_mode == "jetstream"

        async def handler(msg):
            await self._dispatch(table_name, msg.data)
            if is_jetstream:
                await msg.ack()

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
                    "[%s] JetStream subscribe '%s' → table '%s' (durable=%s)",
                    self.name, cfg.topic, table_name, cfg.durable or "<ephemeral>",
                )
            except Exception as e:
                logger.error(
                    "[%s] !! TABLE '%s' WILL RECEIVE NO DATA !! "
                    "JetStream subscribe to '%s' (durable=%s) failed: %s. "
                    "Likely cause: no JetStream stream covers this subject. "
                    "Either create a stream on the broker, or set nats_mode='core' "
                    "on this table to use a non-persistent core NATS subscribe.",
                    self.name, table_name, cfg.topic, cfg.durable, e,
                )
        else:
            await self._nc.subscribe(cfg.topic, cb=handler)
            logger.info(
                "[%s] core subscribe '%s' → table '%s'",
                self.name, cfg.topic, table_name,
            )

    async def disconnect(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._connected = False
            logger.info("[%s] NATSConnector: disconnected", self.name)
