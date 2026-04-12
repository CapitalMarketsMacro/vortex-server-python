from __future__ import annotations
import asyncio

from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.observability import get_logger

logger = get_logger(__name__)

try:
    from solace.messaging.messaging_service import MessagingService
    from solace.messaging.resources.topic_subscription import TopicSubscription
    from solace.messaging.receiver.message_receiver import MessageHandler
    _SOLACE_AVAILABLE = True
except ImportError:
    _SOLACE_AVAILABLE = False
    logger.warning("solace.import_failed", hint="solace-pubsubplus not installed")


class SolaceConnector(BaseConnector):
    def __init__(self, transport, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._service = None
        self._receiver = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _do_connect(self) -> None:
        if not _SOLACE_AVAILABLE:
            raise RuntimeError("solace-pubsubplus unavailable")

        self._loop = asyncio.get_running_loop()
        cfg = self.transport.config

        host = cfg.get("host", "localhost")
        port = int(cfg.get("port", 55555))
        broker_props = {
            "solace.messaging.transport.host": f"tcp://{host}:{port}",
            "solace.messaging.service.vpn-name": cfg.get("vpn", "default"),
            "solace.messaging.authentication.scheme.basic.username": cfg.get("username", ""),
            "solace.messaging.authentication.scheme.basic.password": cfg.get("password", ""),
            # SDK-managed reconnection
            "solace.messaging.transport.reconnection.attempts": "-1",
            "solace.messaging.transport.reconnection.attempts.wait-interval": "3000",
            "solace.messaging.transport.connection-retries": "5",
        }

        self._service = (
            MessagingService.builder()
            .from_properties(broker_props)
            .build()
        )
        # Solace connect is blocking — run in executor so we don't block the loop
        await self._loop.run_in_executor(None, self._service.connect)
        logger.info("solace.connected", host=host, vpn=cfg.get("vpn"))

    async def _do_subscribe(self) -> None:
        if not _SOLACE_AVAILABLE:
            return

        configs: list[TableConfig] = self.registry.tables_by_transport(self.name)
        if not configs:
            logger.info("solace.no_tables", transport=self.name)
            return

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
        logger.info("solace.subscribed", count=len(subscriptions))

    async def _do_disconnect(self) -> None:
        loop = self._loop or asyncio.get_running_loop()
        if self._receiver is not None:
            try:
                await loop.run_in_executor(None, self._receiver.terminate)
            except Exception:
                logger.exception("solace.receiver_terminate_failed")
            finally:
                self._receiver = None
        if self._service is not None:
            try:
                await loop.run_in_executor(None, self._service.disconnect)
            except Exception:
                logger.exception("solace.service_disconnect_failed")
            finally:
                self._service = None
        logger.info("solace.disconnected_clean")
