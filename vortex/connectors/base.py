from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any

from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.config.table_config import TransportConfig
from vortex.observability import (
    get_logger,
    ExponentialBackoff,
    bind_context,
    metrics,
)

logger = get_logger(__name__)


class BaseConnector(ABC):
    """
    Abstract base for all inbound data source connectors.

    Lifecycle (managed by the server orchestrator):
        connector.start()        — fires off a supervisor task; never raises
        connector.stop(timeout)  — sets a flag, cancels supervisor, drains, releases resources

    Supervisor loop (internal):
        while not stopping:
            try:
                _do_connect()        — subclass: open the underlying connection
                _do_subscribe()      — subclass: register subscriptions
                _wait_until_done()   — subclass: block while healthy
            except CancelledError:
                propagate
            except Exception:
                log + sleep with exponential backoff
            finally:
                _do_disconnect()

    Subclasses implement the four `_do_*` and `_wait_until_done` hooks.
    They never need to touch retry logic, gauges, or task management.
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

        self._stopping = asyncio.Event()
        self._supervisor_task: asyncio.Task | None = None
        self._connected = asyncio.Event()
        self._backoff = ExponentialBackoff(initial=1.0, factor=2.0, cap=60.0, jitter=0.5)

    # ── Public lifecycle ────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.transport.name

    @property
    def type(self) -> str:
        return self.transport.type

    def is_up(self) -> bool:
        return self._connected.is_set()

    async def start(self) -> None:
        """Start the supervisor task. Returns immediately, never raises."""
        if self._supervisor_task is not None:
            return
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name=f"sup-{self.name}"
        )
        logger.info("connector.start", transport=self.name, type=self.type)

    async def stop(self, timeout: float = 10.0) -> None:
        """
        Signal the supervisor to stop, wait up to `timeout` seconds for it
        to drain. Always releases resources, even on timeout.
        """
        self._stopping.set()
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            try:
                await asyncio.wait_for(self._supervisor_task, timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                logger.exception("connector.stop.supervisor_error", transport=self.name)
        try:
            await self._do_disconnect()
        except Exception:
            logger.exception("connector.stop.disconnect_error", transport=self.name)
        self._connected.clear()
        metrics.CONNECTOR_UP.labels(transport=self.name, type=self.type).set(0)
        logger.info("connector.stopped", transport=self.name)

    # ── Hot path ────────────────────────────────────────────────────────────

    async def _dispatch(self, table_name: str, payload: bytes | dict | list) -> None:
        """
        Hand a raw payload to the router. Increments counters and contains
        any per-message exception so the read loop never dies.
        """
        try:
            table = self.registry.get(table_name)
        except KeyError:
            metrics.MESSAGES_DROPPED.labels(transport=self.name, reason="unknown_table").inc()
            logger.warning(
                "dispatch.unknown_table", transport=self.name, table=table_name
            )
            return

        metrics.MESSAGES_RECEIVED.labels(transport=self.name, table=table_name).inc()
        try:
            with metrics.MESSAGE_DISPATCH_SECONDS.labels(table=table_name).time():
                await self.router.route(table, payload)
        except Exception:
            metrics.MESSAGES_DROPPED.labels(transport=self.name, reason="dispatch_error").inc()
            logger.exception(
                "dispatch.error", transport=self.name, table=table_name
            )

    # ── Supervisor ──────────────────────────────────────────────────────────

    async def _supervise(self) -> None:
        with bind_context(transport=self.name, transport_type=self.type):
            await self._supervise_inner()

    async def _supervise_inner(self) -> None:
        first = True
        while not self._stopping.is_set():
            if not first:
                metrics.CONNECTOR_RESTARTS.labels(
                    transport=self.name, type=self.type
                ).inc()
            first = False

            try:
                logger.info("connector.connecting")
                await self._do_connect()
                await self._do_subscribe()
                self._connected.set()
                metrics.CONNECTOR_UP.labels(transport=self.name, type=self.type).set(1)
                self._backoff.reset()
                logger.info("connector.connected")

                await self._wait_until_done()

            except asyncio.CancelledError:
                logger.info("connector.cancelled")
                raise
            except Exception as e:
                logger.error(
                    "connector.error",
                    error_type=e.__class__.__name__,
                    error=str(e),
                    exc_info=True,
                )
            finally:
                self._connected.clear()
                metrics.CONNECTOR_UP.labels(transport=self.name, type=self.type).set(0)
                try:
                    await self._do_disconnect()
                except Exception:
                    logger.exception("connector.disconnect_cleanup_error")

            if self._stopping.is_set():
                break

            delay = self._backoff.next()
            logger.warning("connector.reconnect_scheduled", delay_seconds=round(delay, 2))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                break  # stop signalled during the wait
            except asyncio.TimeoutError:
                pass

    # ── Subclass hooks ──────────────────────────────────────────────────────

    @abstractmethod
    async def _do_connect(self) -> None:
        """Open the underlying connection. Raise on failure."""

    @abstractmethod
    async def _do_subscribe(self) -> None:
        """Register all subscriptions for tables that target this transport."""

    @abstractmethod
    async def _do_disconnect(self) -> None:
        """
        Tear down the underlying connection. Must be idempotent and tolerate
        being called multiple times, including after a failed connect.
        """

    async def _wait_until_done(self) -> None:
        """
        Block while the connector is healthy. The default implementation
        blocks until stop() is called. Subclasses may override to detect
        upstream connection loss earlier and trigger an explicit reconnect.
        """
        await self._stopping.wait()
