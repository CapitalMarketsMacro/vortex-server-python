from __future__ import annotations
import asyncio
import logging
import websockets
from websockets.exceptions import ConnectionClosed
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig, TransportConfig

logger = logging.getLogger(__name__)


class WSSourceConnector(BaseConnector):
    def __init__(self, transport: TransportConfig, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._ws = None
        self._task: asyncio.Task | None = None
        self._configs: list[TableConfig] = []

    @property
    def _url(self) -> str:
        return self.transport.config.get("url", "ws://localhost:9000/feed")

    @property
    def _reconnect_interval(self) -> float:
        return float(self.transport.config.get("reconnect_interval", 5.0))

    async def connect(self) -> None:
        self._connected = True
        logger.info("[%s] WSSourceConnector: will connect to %s", self.name, self._url)

    async def subscribe_all(self) -> None:
        self._configs = self.registry.tables_by_transport(self.name)
        if not self._configs:
            logger.info("[%s] no tables configured, skipping", self.name)
            return
        self._task = asyncio.create_task(self._run_loop(), name=f"ws-src-{self.name}")

    async def _run_loop(self) -> None:
        """Reconnecting receive loop. All messages route to the first table."""
        cfg = self._configs[0]
        while True:
            try:
                logger.info("[%s] connecting to %s", self.name, self._url)
                async with websockets.connect(self._url) as ws:
                    self._ws = ws
                    logger.info("[%s] connected", self.name)
                    async for message in ws:
                        payload = (
                            message if isinstance(message, (bytes, bytearray))
                            else message.encode()
                        )
                        await self._dispatch(cfg.name, payload)
            except ConnectionClosed as e:
                logger.warning("[%s] connection closed: %s", self.name, e)
            except Exception:
                logger.exception("[%s] unexpected error", self.name)
            finally:
                self._ws = None

            logger.info("[%s] reconnecting in %.1fs", self.name, self._reconnect_interval)
            await asyncio.sleep(self._reconnect_interval)

    async def disconnect(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        self._connected = False
        logger.info("[%s] WSSourceConnector: disconnected", self.name)
