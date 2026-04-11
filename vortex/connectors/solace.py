from __future__ import annotations
import asyncio
import logging
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig, TransportConfig

logger = logging.getLogger(__name__)

try:
    from solace.messaging.messaging_service import MessagingService
    from solace.messaging.resources.topic_subscription import TopicSubscription
    from solace.messaging.receiver.message_receiver import MessageHandler
    _SOLACE_AVAILABLE = True
except ImportError:
    _SOLACE_AVAILABLE = False
    logger.warning(
        "solace-pubsubplus not installed or import failed — SolaceConnector disabled"
    )


class SolaceConnector(BaseConnector):
    def __init__(self, transport: TransportConfig, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._service = None
        self._receiver = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        if not _SOLACE_AVAILABLE:
            logger.error("[%s] solace-pubsubplus unavailable, skipping connect", self.name)
            return

        self._loop = asyncio.get_running_loop()
        cfg = self.transport.config

        host = cfg.get("host", "localhost")
        port = int(cfg.get("port", 55555))
        broker_props = {
            "solace.messaging.transport.host": f"tcp://{host}:{port}",
            "solace.messaging.service.vpn-name": cfg.get("vpn", "default"),
            "solace.messaging.authentication.scheme.basic.username": cfg.get("username", ""),
            "solace.messaging.authentication.scheme.basic.password": cfg.get("password", ""),
        }

        self._service = (
            MessagingService.builder()
            .from_properties(broker_props)
            .build()
        )
        await self._loop.run_in_executor(None, self._service.connect)
        self._connected = True
        logger.info(
            "[%s] SolaceConnector: connected to %s vpn=%s",
            self.name, host, cfg.get("vpn"),
        )

    async def subscribe_all(self) -> None:
        if not self._connected or not _SOLACE_AVAILABLE:
            return

        configs: list[TableConfig] = self.registry.tables_by_transport(self.name)
        subscriptions = [TopicSubscription.of(cfg.topic) for cfg in configs]
        name_map = {cfg.topic: cfg.name for cfg in configs}

        loop = self._loop
        connector_self = self

        class VortexMessageHandler(MessageHandler):
            def on_message(self, message):
                topic = str(message.get_destination_name())
                table_name = None
                for pattern, name in name_map.items():
                    prefix = pattern.rstrip(">").rstrip("/")
                    if topic.startswith(prefix):
                        table_name = name
                        break
                if table_name is None:
                    return
                payload = message.get_payload_as_bytes()
                asyncio.run_coroutine_threadsafe(
                    connector_self._dispatch(table_name, payload), loop
                )

        self._receiver = (
            self._service
            .create_direct_message_receiver_builder()
            .with_subscriptions(subscriptions)
            .build()
        )
        self._receiver.start()
        self._receiver.receive_async(VortexMessageHandler())
        logger.info("[%s] subscribed to %d topic(s)", self.name, len(subscriptions))

    async def disconnect(self) -> None:
        if self._receiver:
            await self._loop.run_in_executor(None, self._receiver.terminate)
        if self._service:
            await self._loop.run_in_executor(None, self._service.disconnect)
        self._connected = False
        logger.info("[%s] SolaceConnector: disconnected", self.name)
