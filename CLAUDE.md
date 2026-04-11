# VortexServerPython — Claude Code Instructions

> **Project:** `vortex-server-python`
> **Purpose:** A Perspective (FINOS) view server in Python that ingests data from Solace PubSub+, NATS JetStream, and plain WebSocket sources and serves hosted tables to Angular/OpenFin clients via the Perspective WebSocket protocol.
> **Read this file fully before writing any code.** Follow the phases in order. Do not skip ahead.

---

## 0. Orientation

You are building a Python server called **VortexServerPython**. The core technology is [`perspective-python`](https://pypi.org/project/perspective-python/), which embeds the Perspective C++ engine and provides a Tornado WebSocket handler that speaks the Perspective protocol. Angular and OpenFin clients running `@finos/perspective` will connect via `perspective.websocket("ws://host/websocket")` and call `open_table("table_name")` to get a live-updating table proxy.

The server has three inbound data sources, each implemented as an async connector class:
- **Solace PubSub+** via `solace-pubsubplus` (thread-based API, bridge to asyncio)
- **NATS JetStream** via `nats-py` (native asyncio)
- **Plain WebSocket** via `websockets` (native asyncio, acts as a client to an upstream feed)

All three funnel updates through a shared `UpdateRouter` that calls `table.update()` on the appropriate Perspective table.

The Tornado IOLoop is the single event loop. Everything runs in one process, one loop.

---

## 1. Project bootstrap

### 1.1 Create the directory structure

```bash
mkdir -p vortex-server-python/{vortex/connectors,vortex/config,tests,scripts}
cd vortex-server-python
```

### 1.2 Create `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "vortex-server-python"
version = "0.1.0"
description = "Perspective view server — Solace, NATS, WebSocket ingest"
requires-python = ">=3.11"
dependencies = [
    "perspective-python>=3.4",
    "tornado>=6.4",
    "nats-py[nkeys]>=2.9",
    "solace-pubsubplus>=1.8",
    "websockets>=12.0",
    "orjson>=3.10",
    "pydantic-settings>=2.4",
    "pyyaml>=6.0",
    "pyarrow>=16.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 1.3 Create a virtual environment and install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> **Note for Claude Code:** If `perspective-python` takes a long time to install, that is normal — it compiles native extensions. Do not interrupt the install. If it fails, check that Python 3.11+ is active and that `cmake` and a C++ compiler are available on the system. On Debian/Ubuntu: `sudo apt-get install -y cmake build-essential`.

---

## 2. Configuration layer

### 2.1 Create `vortex/config/settings.py`

This file defines all runtime configuration using `pydantic-settings`. Values are read from environment variables (uppercase, prefixed with `VORTEX_`). Every field has a sensible default so the server can start for local development without any env vars set.

```python
# vortex/config/settings.py
from __future__ import annotations
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class SolaceSettings(BaseModel):
    host: str = "localhost"
    vpn: str = "default"
    username: str = "admin"
    password: str = "admin"
    port: int = 55555


class NATSSettings(BaseModel):
    url: str = "nats://localhost:4222"
    user: str | None = None
    password: str | None = None
    token: str | None = None


class WSSourceSettings(BaseModel):
    url: str = "ws://localhost:9000/feed"
    reconnect_interval: float = 5.0


class VortexSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VORTEX_",
        env_nested_delimiter="__",
    )

    port: int = 8080
    host: str = "0.0.0.0"
    tables_config: str = "vortex/config/tables.yaml"
    log_level: str = "INFO"

    solace: SolaceSettings = SolaceSettings()
    nats: NATSSettings = NATSSettings()
    ws_source: WSSourceSettings = WSSourceSettings()

    enable_solace: bool = True
    enable_nats: bool = True
    enable_ws_source: bool = True


def load_settings() -> VortexSettings:
    return VortexSettings()
```

### 2.2 Create `vortex/config/tables.yaml`

This is the declarative table registry. Each entry maps a table name to a schema, an update semantic, and a source subscription.

```yaml
# vortex/config/tables.yaml
# Schema types: string, float, integer, boolean, datetime, date
# source: solace | nats | ws
# For upsert tables: set index to the primary key column name.
# For append/rolling tables: set limit (omit index).

tables:
  - name: fx_executions
    source: solace
    topic: "FX/EXEC/>"
    schema:
      exec_id: string
      ccy_pair: string
      side: string
      notional: float
      px: float
      spot_rate: float
      value_date: date
      venue: string
      trader: string
      ts: datetime
    limit: 5000

  - name: ust_trades
    source: nats
    subject: "rates.ust.trades.>"
    durable: vortex-ust-trades
    schema:
      trade_id: string
      isin: string
      cusip: string
      side: string
      qty: float
      price: float
      yield: float
      spread_to_benchmark: float
      trader: string
      ts: datetime
    index: trade_id

  - name: live_prices
    source: ws
    schema:
      instrument: string
      bid: float
      ask: float
      mid: float
      bid_size: float
      ask_size: float
      ts: datetime
    index: instrument
```

### 2.3 Create `vortex/config/__init__.py`

```python
# vortex/config/__init__.py
from .settings import VortexSettings, load_settings

__all__ = ["VortexSettings", "load_settings"]
```

### 2.4 Create the table config loader in `vortex/config/table_config.py`

```python
# vortex/config/table_config.py
from __future__ import annotations
from dataclasses import dataclass, field
import yaml

# Map YAML type strings to Python types that perspective-python accepts
_TYPE_MAP: dict[str, type] = {
    "string": str,
    "float": float,
    "integer": int,
    "boolean": bool,
    "datetime": "datetime",  # perspective uses the string "datetime"
    "date": "date",
}


@dataclass
class TableConfig:
    name: str
    source: str                         # "solace" | "nats" | "ws"
    schema: dict[str, type | str]
    topic: str = ""                     # Solace topic
    subject: str = ""                   # NATS subject
    durable: str | None = None          # NATS durable consumer name
    index: str | None = None            # upsert primary key
    limit: int | None = None            # rolling append window


def load_table_configs(path: str) -> list[TableConfig]:
    with open(path) as f:
        raw = yaml.safe_load(f)

    configs = []
    for entry in raw.get("tables", []):
        schema = {
            col: _TYPE_MAP.get(typ, str)
            for col, typ in entry["schema"].items()
        }
        configs.append(
            TableConfig(
                name=entry["name"],
                source=entry["source"],
                schema=schema,
                topic=entry.get("topic", ""),
                subject=entry.get("subject", ""),
                durable=entry.get("durable"),
                index=entry.get("index"),
                limit=entry.get("limit"),
            )
        )
    return configs
```

---

## 3. Core engine — TableRegistry

### 3.1 Create `vortex/registry.py`

```python
# vortex/registry.py
from __future__ import annotations
import logging
from vortex.config.table_config import TableConfig

logger = logging.getLogger(__name__)


class TableRegistry:
    """
    Owns all Perspective Table instances.
    Created once at startup; connector threads and the Tornado loop
    both read from it (read is safe; update() is called from the loop).
    """

    def __init__(self, client) -> None:
        self._client = client
        self._tables: dict[str, object] = {}
        self._configs: dict[str, TableConfig] = {}

    def register(self, cfg: TableConfig) -> object:
        """Create and register a Perspective Table for the given config."""
        kwargs: dict = {}
        if cfg.index:
            kwargs["index"] = cfg.index
        if cfg.limit:
            kwargs["limit"] = cfg.limit

        table = self._client.table(cfg.schema, name=cfg.name, **kwargs)
        self._tables[cfg.name] = table
        self._configs[cfg.name] = cfg
        logger.info(
            "Registered table '%s'  index=%s  limit=%s  source=%s",
            cfg.name, cfg.index, cfg.limit, cfg.source,
        )
        return table

    def get(self, name: str):
        if name not in self._tables:
            raise KeyError(f"No table registered with name '{name}'")
        return self._tables[name]

    def all_tables(self) -> dict[str, object]:
        return dict(self._tables)

    def tables_by_source(self, source: str) -> list[TableConfig]:
        return [c for c in self._configs.values() if c.source == source]
```

---

## 4. UpdateRouter

### 4.1 Create `vortex/router.py`

```python
# vortex/router.py
from __future__ import annotations
import logging
import orjson

logger = logging.getLogger(__name__)

# Apache Arrow IPC stream magic bytes (first 4 bytes = continuation marker,
# next 4 = schema message marker). In practice check for the ARROW1 magic.
_ARROW_MAGIC = b"\xff\xff\xff\xff"   # IPC stream starts with continuation marker


class UpdateRouter:
    """
    Receives raw payloads from connectors and calls table.update().

    Payload handling:
        bytes starting with Arrow IPC magic  →  passed as-is (fastest path)
        bytes (other)                        →  decoded as UTF-8 JSON
        dict / list[dict]                    →  passed directly
    """

    async def route(self, table, payload: bytes | dict | list) -> None:
        try:
            if isinstance(payload, (bytes, bytearray)):
                if payload[:4] == _ARROW_MAGIC:
                    table.update(bytes(payload))
                else:
                    data = orjson.loads(payload)
                    table.update(data if isinstance(data, list) else [data])
            elif isinstance(payload, dict):
                table.update([payload])
            elif isinstance(payload, list):
                table.update(payload)
            else:
                logger.warning("UpdateRouter: unhandled payload type %s", type(payload))
        except Exception:
            logger.exception("UpdateRouter: failed to update table")
```

---

## 5. Connector layer

### 5.1 Create `vortex/connectors/__init__.py`

```python
# vortex/connectors/__init__.py
from .base import BaseConnector
from .nats import NATSConnector
from .solace import SolaceConnector
from .websocket_src import WSSourceConnector

__all__ = ["BaseConnector", "NATSConnector", "SolaceConnector", "WSSourceConnector"]
```

### 5.2 Create `vortex/connectors/base.py`

```python
# vortex/connectors/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
import logging
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """
    Abstract base for all inbound data source connectors.

    Subclasses must implement:
        connect()     — establish connection to the source
        subscribe()   — register subscriptions for all tables owned by this source
        disconnect()  — tear down cleanly

    _dispatch() is the common hot path — call it from every message handler.
    """

    def __init__(self, registry: TableRegistry, router: UpdateRouter) -> None:
        self.registry = registry
        self.router = router
        self._connected = False

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def subscribe_all(self) -> None:
        """Subscribe to all topics/subjects mapped to this connector's source type."""
        ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    async def _dispatch(self, table_name: str, payload: bytes | dict | list) -> None:
        try:
            table = self.registry.get(table_name)
        except KeyError:
            logger.warning("_dispatch: no table '%s', dropping message", table_name)
            return
        await self.router.route(table, payload)
```

### 5.3 Create `vortex/connectors/nats.py`

NATS is the simplest connector — `nats-py` is native asyncio, no thread bridging required.

```python
# vortex/connectors/nats.py
from __future__ import annotations
import logging
import nats
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.config.settings import NATSSettings

logger = logging.getLogger(__name__)


class NATSConnector(BaseConnector):
    def __init__(self, settings: NATSSettings, registry, router) -> None:
        super().__init__(registry, router)
        self._settings = settings
        self._nc = None
        self._js = None

    async def connect(self) -> None:
        connect_kwargs: dict = {"servers": self._settings.url}
        if self._settings.user:
            connect_kwargs["user"] = self._settings.user
            connect_kwargs["password"] = self._settings.password
        if self._settings.token:
            connect_kwargs["token"] = self._settings.token

        self._nc = await nats.connect(**connect_kwargs)
        self._js = self._nc.jetstream()
        self._connected = True
        logger.info("NATSConnector: connected to %s", self._settings.url)

    async def subscribe_all(self) -> None:
        configs: list[TableConfig] = self.registry.tables_by_source("nats")
        for cfg in configs:
            await self._subscribe_one(cfg)

    async def _subscribe_one(self, cfg: TableConfig) -> None:
        table_name = cfg.name

        async def handler(msg):
            await self._dispatch(table_name, msg.data)
            await msg.ack()

        if cfg.durable:
            # JetStream durable push consumer — survives restarts
            try:
                await self._js.subscribe(
                    cfg.subject,
                    durable=cfg.durable,
                    cb=handler,
                    deliver_policy=nats.js.api.DeliverPolicy.NEW,
                )
                logger.info(
                    "NATSConnector: JetStream subscribe '%s' → table '%s' (durable=%s)",
                    cfg.subject, table_name, cfg.durable,
                )
            except Exception:
                logger.exception(
                    "NATSConnector: failed JetStream subscribe for '%s'", cfg.subject
                )
        else:
            # Core NATS — ephemeral, no persistence
            await self._nc.subscribe(cfg.subject, cb=handler)
            logger.info(
                "NATSConnector: core subscribe '%s' → table '%s'",
                cfg.subject, table_name,
            )

    async def disconnect(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._connected = False
            logger.info("NATSConnector: disconnected")
```

### 5.4 Create `vortex/connectors/solace.py`

Solace's Python API is thread-based and uses callbacks. Bridge to asyncio with `run_coroutine_threadsafe`.

```python
# vortex/connectors/solace.py
from __future__ import annotations
import asyncio
import logging
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.config.settings import SolaceSettings

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
    def __init__(self, settings: SolaceSettings, registry, router) -> None:
        super().__init__(registry, router)
        self._settings = settings
        self._service = None
        self._receiver = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        if not _SOLACE_AVAILABLE:
            logger.error("SolaceConnector: solace-pubsubplus unavailable, skipping connect")
            return

        self._loop = asyncio.get_running_loop()

        broker_props = {
            "solace.messaging.transport.host": (
                f"tcp://{self._settings.host}:{self._settings.port}"
            ),
            "solace.messaging.service.vpn-name": self._settings.vpn,
            "solace.messaging.authentication.scheme.basic.username": self._settings.username,
            "solace.messaging.authentication.scheme.basic.password": self._settings.password,
        }

        self._service = (
            MessagingService.builder()
            .from_properties(broker_props)
            .build()
        )
        # connect() is blocking — run in executor so we don't block the loop
        await self._loop.run_in_executor(None, self._service.connect)
        self._connected = True
        logger.info(
            "SolaceConnector: connected to %s vpn=%s",
            self._settings.host, self._settings.vpn,
        )

    async def subscribe_all(self) -> None:
        if not self._connected or not _SOLACE_AVAILABLE:
            return

        configs: list[TableConfig] = self.registry.tables_by_source("solace")
        subscriptions = [TopicSubscription.of(cfg.topic) for cfg in configs]
        name_map = {cfg.topic: cfg.name for cfg in configs}

        loop = self._loop

        class VortexMessageHandler(MessageHandler):
            def __init__(self, connector: SolaceConnector):
                self._connector = connector

            def on_message(self, message):
                topic = str(message.get_destination_name())
                # Find which table_name this topic maps to
                # Use prefix matching: topic "FX/EXEC/>" matches message "FX/EXEC/USD/EUR"
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
                    self._connector._dispatch(table_name, payload), loop
                )

        self._receiver = (
            self._service
            .create_direct_message_receiver_builder()
            .with_subscriptions(subscriptions)
            .build()
        )
        self._receiver.start()
        self._receiver.receive_async(VortexMessageHandler(self))
        logger.info(
            "SolaceConnector: subscribed to %d topic(s)",
            len(subscriptions),
        )

    async def disconnect(self) -> None:
        if self._receiver:
            await self._loop.run_in_executor(None, self._receiver.terminate)
        if self._service:
            await self._loop.run_in_executor(None, self._service.disconnect)
        self._connected = False
        logger.info("SolaceConnector: disconnected")
```

### 5.5 Create `vortex/connectors/websocket_src.py`

This connector acts as a **client** to an upstream WebSocket feed. It reconnects automatically on disconnect.

```python
# vortex/connectors/websocket_src.py
from __future__ import annotations
import asyncio
import logging
import websockets
from websockets.exceptions import ConnectionClosed
from vortex.connectors.base import BaseConnector
from vortex.config.table_config import TableConfig
from vortex.config.settings import WSSourceSettings

logger = logging.getLogger(__name__)


class WSSourceConnector(BaseConnector):
    def __init__(self, settings: WSSourceSettings, registry, router) -> None:
        super().__init__(registry, router)
        self._settings = settings
        self._ws = None
        self._task: asyncio.Task | None = None
        self._configs: list[TableConfig] = []

    async def connect(self) -> None:
        # Connection is established lazily in subscribe_all → _run_loop
        self._connected = True
        logger.info("WSSourceConnector: will connect to %s", self._settings.url)

    async def subscribe_all(self) -> None:
        self._configs = self.registry.tables_by_source("ws")
        if not self._configs:
            logger.info("WSSourceConnector: no ws tables configured, skipping")
            return
        # All ws messages go to all ws tables — route by message field if needed
        # For now: single ws source → single ws table (first one)
        self._task = asyncio.create_task(self._run_loop(), name="ws-src-loop")

    async def _run_loop(self) -> None:
        """Reconnecting receive loop."""
        cfg = self._configs[0]   # primary ws table
        while True:
            try:
                logger.info("WSSourceConnector: connecting to %s", self._settings.url)
                async with websockets.connect(self._settings.url) as ws:
                    self._ws = ws
                    logger.info("WSSourceConnector: connected")
                    async for message in ws:
                        payload = (
                            message if isinstance(message, (bytes, bytearray))
                            else message.encode()
                        )
                        await self._dispatch(cfg.name, payload)
            except ConnectionClosed as e:
                logger.warning("WSSourceConnector: connection closed: %s", e)
            except Exception:
                logger.exception("WSSourceConnector: unexpected error")
            finally:
                self._ws = None

            logger.info(
                "WSSourceConnector: reconnecting in %.1fs",
                self._settings.reconnect_interval,
            )
            await asyncio.sleep(self._settings.reconnect_interval)

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
        logger.info("WSSourceConnector: disconnected")
```

---

## 6. Health endpoint

### 6.1 Create `vortex/health.py`

```python
# vortex/health.py
import json
import tornado.web


class HealthHandler(tornado.web.RequestHandler):
    """
    GET /health  →  200 {"status": "ok", "tables": [...]}
    Used as OpenShift readiness probe.
    """

    def initialize(self, registry):
        self._registry = registry

    def get(self):
        tables = list(self._registry.all_tables().keys())
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"status": "ok", "tables": tables}))
```

---

## 7. Main server entry point

### 7.1 Create `vortex/server.py`

```python
# vortex/server.py
from __future__ import annotations
import asyncio
import logging
import signal

import perspective
import tornado.web
import tornado.ioloop
from perspective.handlers.tornado import PerspectiveTornadoHandler

from vortex.config.settings import load_settings
from vortex.config.table_config import load_table_configs
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.health import HealthHandler
from vortex.connectors.nats import NATSConnector
from vortex.connectors.solace import SolaceConnector
from vortex.connectors.websocket_src import WSSourceConnector


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


def make_tornado_app(psp_server, registry) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (
                r"/websocket",
                PerspectiveTornadoHandler,
                {"perspective_server": psp_server},
            ),
            (
                r"/health",
                HealthHandler,
                {"registry": registry},
            ),
        ],
        websocket_ping_interval=30,
        websocket_ping_timeout=120,
    )


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("vortex.server")

    logger.info("Starting VortexServerPython on %s:%d", settings.host, settings.port)

    # ── Perspective engine ──────────────────────────────────────────────────
    psp_server = perspective.Server()
    local_client = psp_server.new_local_client()

    # ── Table registry ──────────────────────────────────────────────────────
    table_configs = load_table_configs(settings.tables_config)
    registry = TableRegistry(local_client)
    for cfg in table_configs:
        registry.register(cfg)

    # ── Update router ───────────────────────────────────────────────────────
    router = UpdateRouter()

    # ── Connectors ──────────────────────────────────────────────────────────
    connectors = []

    if settings.enable_nats:
        connectors.append(NATSConnector(settings.nats, registry, router))

    if settings.enable_solace:
        connectors.append(SolaceConnector(settings.solace, registry, router))

    if settings.enable_ws_source:
        connectors.append(WSSourceConnector(settings.ws_source, registry, router))

    for conn in connectors:
        await conn.connect()
        await conn.subscribe_all()

    # ── Tornado app ─────────────────────────────────────────────────────────
    app = make_tornado_app(psp_server, registry)
    server = app.listen(settings.port, settings.host)
    logger.info("Perspective WebSocket endpoint: ws://%s:%d/websocket", settings.host, settings.port)
    logger.info("Health endpoint:                http://%s:%d/health", settings.host, settings.port)

    # ── Graceful shutdown ───────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)

    await stop_event.wait()

    logger.info("Shutting down connectors...")
    for conn in connectors:
        await conn.disconnect()

    server.stop()
    logger.info("VortexServerPython stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
```

### 7.2 Add the entry point to `pyproject.toml`

Append this section to `pyproject.toml`:

```toml
[project.scripts]
vortex-server = "vortex.server:run"
```

---

## 8. Package `__init__.py` files

```python
# vortex/__init__.py
"""VortexServerPython — Perspective view server."""
```

```python
# vortex/connectors/__init__.py
from .base import BaseConnector
from .nats import NATSConnector
from .solace import SolaceConnector
from .websocket_src import WSSourceConnector

__all__ = ["BaseConnector", "NATSConnector", "SolaceConnector", "WSSourceConnector"]
```

---

## 9. Dockerfile

```dockerfile
FROM python:3.11-slim

# Build deps for perspective-python native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake build-essential libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY vortex/ ./vortex/

EXPOSE 8080

CMD ["vortex-server"]
```

---

## 10. Tests

### 10.1 Create `tests/conftest.py`

```python
# tests/conftest.py
import pytest
import perspective
from unittest.mock import AsyncMock, MagicMock
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.config.table_config import TableConfig


@pytest.fixture
def psp_client():
    server = perspective.Server()
    return server.new_local_client()


@pytest.fixture
def registry(psp_client):
    return TableRegistry(psp_client)


@pytest.fixture
def router():
    return UpdateRouter()


@pytest.fixture
def sample_table_config():
    return TableConfig(
        name="test_prices",
        source="nats",
        subject="test.prices.>",
        schema={"instrument": str, "bid": float, "ask": float},
        index="instrument",
    )
```

### 10.2 Create `tests/test_registry.py`

```python
# tests/test_registry.py
import pytest
from vortex.registry import TableRegistry
from vortex.config.table_config import TableConfig


def test_register_and_get(registry, sample_table_config):
    table = registry.register(sample_table_config)
    assert table is not None
    assert registry.get("test_prices") is table


def test_get_missing_raises(registry):
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_tables_by_source(registry):
    cfg1 = TableConfig("t1", "nats", {"a": str}, subject="a.>", index="a")
    cfg2 = TableConfig("t2", "solace", {"b": str}, topic="B/>")
    registry.register(cfg1)
    registry.register(cfg2)
    nats_cfgs = registry.tables_by_source("nats")
    assert len(nats_cfgs) == 1
    assert nats_cfgs[0].name == "t1"
```

### 10.3 Create `tests/test_router.py`

```python
# tests/test_router.py
import pytest
import orjson
from vortex.router import UpdateRouter


@pytest.mark.asyncio
async def test_route_dict(registry, sample_table_config):
    registry.register(sample_table_config)
    router = UpdateRouter()
    table = registry.get("test_prices")

    await router.route(table, {"instrument": "EURUSD", "bid": 1.08, "ask": 1.0801})

    view = table.view()
    data = view.to_columns()
    assert data["instrument"] == ["EURUSD"]
    assert data["bid"] == [1.08]


@pytest.mark.asyncio
async def test_route_json_bytes(registry, sample_table_config):
    registry.register(sample_table_config)
    router = UpdateRouter()
    table = registry.get("test_prices")

    payload = orjson.dumps({"instrument": "GBPUSD", "bid": 1.27, "ask": 1.2701})
    await router.route(table, payload)

    view = table.view()
    data = view.to_columns()
    assert "GBPUSD" in data["instrument"]
```

### 10.4 Create `tests/test_nats_connector.py`

```python
# tests/test_nats_connector.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import orjson
from vortex.connectors.nats import NATSConnector
from vortex.config.settings import NATSSettings


@pytest.mark.asyncio
async def test_nats_dispatch_on_message(registry, router, sample_table_config):
    registry.register(sample_table_config)

    settings = NATSSettings(url="nats://localhost:4222")
    connector = NATSConnector(settings, registry, router)

    # Simulate receiving a message
    payload = orjson.dumps({"instrument": "USDJPY", "bid": 149.5, "ask": 149.51})
    await connector._dispatch("test_prices", payload)

    table = registry.get("test_prices")
    view = table.view()
    data = view.to_columns()
    assert "USDJPY" in data["instrument"]
```

---

## 11. Dev simulation scripts

These let you test the server without real Solace/NATS/upstream WS.

### 11.1 Create `scripts/sim_nats_publisher.py`

```python
#!/usr/bin/env python3
"""
Publishes simulated FX price ticks to NATS for local dev testing.
Usage: python scripts/sim_nats_publisher.py
Requires: nats-py, orjson
"""
import asyncio
import random
import orjson
from datetime import datetime, timezone
import nats

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
SUBJECT = "rates.ust.trades.sim"


async def main():
    nc = await nats.connect("nats://localhost:4222")
    print(f"Publishing to NATS subject: {SUBJECT}")
    try:
        while True:
            pair = random.choice(PAIRS)
            base = {"EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 149.5,
                    "AUDUSD": 0.65, "USDCHF": 0.90}[pair]
            spread = 0.0001
            bid = round(base + random.gauss(0, 0.0002), 5)
            ask = round(bid + spread, 5)
            msg = {
                "trade_id": f"T{random.randint(100000,999999)}",
                "isin": f"US{random.randint(10000000,99999999)}{random.randint(0,9)}",
                "cusip": f"{random.randint(100000000,999999999)}",
                "side": random.choice(["BUY", "SELL"]),
                "qty": round(random.uniform(1e6, 50e6), 0),
                "price": round(99 + random.uniform(-1, 1), 4),
                "yield": round(4.5 + random.gauss(0, 0.05), 4),
                "spread_to_benchmark": round(random.uniform(0, 50), 2),
                "trader": random.choice(["trader_a", "trader_b", "trader_c"]),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await nc.publish(SUBJECT, orjson.dumps(msg))
            print(f"  → {msg['trade_id']}  {msg['side']}  {msg['qty']:,.0f}")
            await asyncio.sleep(random.uniform(0.2, 1.0))
    finally:
        await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
```

### 11.2 Create `scripts/sim_ws_feed.py`

```python
#!/usr/bin/env python3
"""
Runs a local WebSocket server that emits simulated FX price ticks.
VortexServerPython's WSSourceConnector connects to this as a client.
Usage: python scripts/sim_ws_feed.py
Set VORTEX_WS_SOURCE__URL=ws://localhost:9000/feed
"""
import asyncio
import random
import orjson
from datetime import datetime, timezone
import websockets

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
BASES = {"EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 149.5, "AUDUSD": 0.65, "USDCHF": 0.90}


async def feed(ws):
    print(f"Client connected: {ws.remote_address}")
    try:
        while True:
            pair = random.choice(PAIRS)
            bid = round(BASES[pair] + random.gauss(0, 0.0002), 5)
            ask = round(bid + 0.0001, 5)
            msg = {
                "instrument": pair,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 5),
                "bid_size": round(random.uniform(1e6, 10e6), 0),
                "ask_size": round(random.uniform(1e6, 10e6), 0),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await ws.send(orjson.dumps(msg))
            await asyncio.sleep(random.uniform(0.05, 0.3))
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")


async def main():
    async with websockets.serve(feed, "localhost", 9000, ping_interval=20):
        print("WS feed server on ws://localhost:9000/feed")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 12. Environment variables reference

For local dev, create a `.env` file or export these before running:

```bash
# Disable unused sources to avoid connection errors locally
export VORTEX_ENABLE_SOLACE=false
export VORTEX_ENABLE_NATS=true
export VORTEX_ENABLE_WS_SOURCE=true

export VORTEX_NATS__URL=nats://localhost:4222
export VORTEX_WS_SOURCE__URL=ws://localhost:9000/feed

export VORTEX_PORT=8080
export VORTEX_LOG_LEVEL=DEBUG
```

For OpenShift, set these as `ConfigMap` + `Secret` and inject via `envFrom`.

---

## 13. Build and run sequence

Run these in order during first-time setup. Follow each step completely before proceeding.

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Run tests (should all pass before running the server)
pytest tests/ -v

# 3. (Terminal A) Start the simulated WS feed
python scripts/sim_ws_feed.py

# 4. (Terminal B — if testing NATS) Start a local NATS server
#    If nats-server is not installed: brew install nats-server  or  apt install nats-server
nats-server -js

# 5. (Terminal C — if testing NATS) Start the NATS publisher
python scripts/sim_nats_publisher.py

# 6. (Terminal D) Start VortexServerPython
VORTEX_ENABLE_SOLACE=false \
VORTEX_ENABLE_NATS=true \
VORTEX_ENABLE_WS_SOURCE=true \
python -m vortex.server

# 7. Verify health endpoint
curl http://localhost:8080/health

# 8. Test from a browser console (with @finos/perspective loaded):
#    const ws = await perspective.websocket("ws://localhost:8080/websocket");
#    const table = await ws.open_table("live_prices");
#    const view = await table.view();
#    view.to_columns().then(console.log);
```

---

## 14. Common failure modes and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `perspective-python` install fails | Missing cmake or C++ compiler | `sudo apt-get install cmake build-essential` |
| `ModuleNotFoundError: perspective` | Wrong venv active | `source .venv/bin/activate` |
| `KeyError` on `open_table` in JS | Table name mismatch | Table name in JS must exactly match `name` in `tables.yaml` |
| Solace `import` fails silently | Package not installed | `pip install solace-pubsubplus`; set `VORTEX_ENABLE_SOLACE=false` to skip |
| NATS JetStream subscribe fails | Stream doesn't exist | Create the stream first: `nats stream add` or disable durable in config |
| Messages arrive but table not updating | Arrow magic mismatch | Check payload format; add logging in `UpdateRouter.route()` |
| Tornado WebSocket 408 timeout | HAProxy `timeout tunnel` too short | Set `timeout tunnel 1h` in HAProxy config |
| High memory in OpenShift pod | Large `limit` on append tables | Reduce `limit` in `tables.yaml` or increase pod memory request |

---

## 15. File checklist

When done, the project tree should look exactly like this:

```
vortex-server-python/
├── pyproject.toml
├── Dockerfile
├── .env                          (gitignored, local only)
├── vortex/
│   ├── __init__.py
│   ├── server.py
│   ├── registry.py
│   ├── router.py
│   ├── health.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── table_config.py
│   │   └── tables.yaml
│   └── connectors/
│       ├── __init__.py
│       ├── base.py
│       ├── nats.py
│       ├── solace.py
│       └── websocket_src.py
├── tests/
│   ├── conftest.py
│   ├── test_registry.py
│   ├── test_router.py
│   └── test_nats_connector.py
└── scripts/
    ├── sim_nats_publisher.py
    └── sim_ws_feed.py
```

All files above must be created before running the server. Do not rename files or change the module paths — the imports in `server.py` depend on this exact structure.
