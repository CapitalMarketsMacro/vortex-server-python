from __future__ import annotations
from abc import ABC, abstractmethod
import logging
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.config.table_config import TransportConfig

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """
    Abstract base for all inbound data source connectors.

    One connector instance per TransportConfig document.
    Subclasses pull their subscription list from
    registry.tables_by_transport(self.transport.name).
    """

    def __init__(
        self,
        transport: TransportConfig,
        registry: TableRegistry,
        router: UpdateRouter,
    ) -> None:
        self.transport = transport
        self.registry = registry
        self.router = router
        self._connected = False

    @property
    def name(self) -> str:
        return self.transport.name

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def subscribe_all(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    async def _dispatch(self, table_name: str, payload: bytes | dict | list) -> None:
        try:
            table = self.registry.get(table_name)
        except KeyError:
            logger.warning(
                "[%s] _dispatch: no table '%s', dropping message",
                self.name, table_name,
            )
            return
        await self.router.route(table, payload)
