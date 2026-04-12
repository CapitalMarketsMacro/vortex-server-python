from __future__ import annotations
import asyncio
import websockets
from websockets.exceptions import ConnectionClosed

from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.observability import get_logger

logger = get_logger(__name__)


class WSSourceConnector(BaseConnector):
    def __init__(self, transport, registry, router) -> None:
        super().__init__(transport, registry, router)
        self._ws = None
        self._configs: list[TableConfig] = []

    @property
    def _url(self) -> str:
        return self.transport.config.get("url", "ws://localhost:9000/feed")

    async def _do_connect(self) -> None:
        self._ws = await websockets.connect(
            self._url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
        logger.info("ws.connected", url=self._url)

    async def _do_subscribe(self) -> None:
        self._configs = self.registry.tables_by_transport(self.name)
        if not self._configs:
            logger.info("ws.no_tables", transport=self.name)

    async def _wait_until_done(self) -> None:
        """
        Read messages until the connection drops or stop is requested.
        Raising ConnectionError triggers the supervisor to restart with backoff.
        """
        if self._ws is None:
            await asyncio.sleep(0.1)
            return
        if not self._configs:
            # No tables — just hold the connection until stop
            await self._stopping.wait()
            return

        cfg = self._configs[0]
        try:
            async for message in self._ws:
                if self._stopping.is_set():
                    return
                payload = (
                    message if isinstance(message, (bytes, bytearray))
                    else message.encode()
                )
                await self._dispatch(cfg.name, payload)
        except ConnectionClosed as e:
            logger.warning("ws.connection_closed", code=e.code, reason=str(e))
            raise ConnectionError(f"ws connection closed: {e}") from e

    async def _do_disconnect(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            finally:
                self._ws = None
                logger.info("ws.disconnected_clean")
