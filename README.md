# VortexServerPython

**A Perspective (FINOS) view server in Python** that ingests real-time data from Solace PubSub+, NATS (core + JetStream), and plain WebSocket sources, then serves hosted tables to Angular / OpenFin / `perspective-viewer` clients over a single WebSocket.

Built for enterprise deployment with dial-tone reliability in mind: supervised connectors with exponential backoff, structured JSON logging, Prometheus metrics, separate liveness / readiness health checks, and a Mongo-backed admin GUI for editing transport and table configuration at runtime.

---

## Architecture

### Data flow

```mermaid
flowchart LR
    subgraph Brokers["External Data Sources"]
        Solace[Solace PubSub+]
        NATS[NATS / JetStream]
        UpstreamWS[Upstream WebSocket]
    end

    subgraph Vortex["Vortex Data Server (Python, one process)"]
        direction TB
        SolConn[SolaceConnector]
        NATSConn[NATSConnector]
        WSConn[WSSourceConnector]
        Router[UpdateRouter]
        Registry[TableRegistry]
        Engine[(Perspective C++ Engine<br/>hosted tables)]
        TornadoWS[Tornado<br/>WebSocketHandler<br/>:8080/websocket]
    end

    Solace -->|topic: FX/EXEC/&gt;| SolConn
    NATS -->|subject: rates.ust.trades.&gt;| NATSConn
    UpstreamWS -->|JSON rows| WSConn

    SolConn --> Router
    NATSConn --> Router
    WSConn --> Router
    Router -->|table.update| Engine
    Registry -.owns.-> Engine
    Engine --> TornadoWS

    subgraph Clients["Downstream Clients"]
        Angular[Angular / OpenFin<br/>perspective-viewer]
        Browser[Browser dashboards]
    end

    TornadoWS -->|Perspective binary<br/>protocol| Angular
    TornadoWS -->|Perspective binary<br/>protocol| Browser
```

Each inbound broker is handled by a **supervised connector task**. Supervisors survive initial connect failure, reconnect with exponential backoff + jitter, and surface their state via the `vortex_connector_up{transport,type}` gauge. One transport failing never affects another — each is its own isolated failure domain.

### Component layout

```mermaid
flowchart TB
    subgraph Configuration["MongoDB — database: Vortex"]
        TransportsCol[(collection: transports<br/>name, type, config, enabled)]
        TablesCol[(collection: tables<br/>name, transport_name, schema,<br/>topic, index/limit, nats_mode)]
    end

    subgraph DataServer["vortex-server  (port 8080)"]
        SrvBoot[server.py bootstrap]
        SrvConns[supervised connectors]
        SrvTables[Perspective tables]
        SrvEndpoints[Endpoints:<br/>/websocket<br/>/health/live<br/>/health/ready<br/>/metrics<br/>/api/status]
        SrvBoot --> SrvConns
        SrvBoot --> SrvTables
        SrvConns --> SrvTables
        SrvTables --> SrvEndpoints
    end

    subgraph AdminGUI["vortex-admin  (port 8090)"]
        AdmRoutes[Flask routes:<br/>/ /status<br/>/transports /tables<br/>/api/tables /api/status]
        AdmTemplates[Jinja templates<br/>+ live status dashboard]
        AdmRoutes --> AdmTemplates
    end

    subgraph Observability["Ops stack"]
        Promo[Prometheus<br/>scrape /metrics]
        Grafana[Grafana<br/>dashboards]
        Promo --> Grafana
    end

    Configuration -->|startup read| DataServer
    Configuration <-->|CRUD| AdminGUI
    AdminGUI -->|proxy /api/status<br/>every 2 s| DataServer
    DataServer --> Promo

    Clients[perspective-viewer<br/>clients] -->|ws://.../websocket| DataServer
```

### Reliability model

```mermaid
stateDiagram-v2
    [*] --> Connecting: supervisor.start()
    Connecting --> Connected: _do_connect ok<br/>_do_subscribe ok
    Connecting --> Backoff: exception
    Connected --> Backoff: _wait_until_done raises<br/>(connection lost)
    Backoff --> Connecting: wait(exp + jitter)<br/>capped at 60s
    Connected --> Stopping: stop() signalled
    Backoff --> Stopping: stop() signalled
    Connecting --> Stopping: stop() signalled
    Stopping --> [*]: _do_disconnect

    note right of Backoff
        1s → 2 → 4 → 8 → 16 → 32 → 60s
        ±50% full jitter.
        Resets on successful connect.
    end note
```

---

## Prerequisites

- **Python 3.11+** (prebuilt `perspective-python` wheels ship for Windows x64, Linux x86_64/aarch64 and macOS arm64 — no C++ build toolchain needed on those platforms)
- **MongoDB 4.4+** — stores transport and table configuration
- **At least one broker** for live data:
  - NATS 2.x (core or JetStream)
  - Solace PubSub+
  - or any WebSocket JSON feed

---

## Quick start (fresh clone)

### 1. Install

```bash
git clone https://github.com/CapitalMarketsMacro/vortex-server-python.git
cd vortex-server-python

# One-shot install — creates .venv, upgrades pip, installs dev extras
scripts/install.sh        # Linux / macOS / Git Bash
scripts\install.bat       # Windows cmd
```

### 2. Configure

```bash
cp .env.example .env
# edit .env — at minimum set VORTEX_MONGO__URI
```

### 3. Seed Mongo with an initial topology

```bash
scripts/seed-mongo.sh     # or .bat
```

This upserts three demo transports (`nats-monty`, `solace-local`, `ws-sim`) and three tables (`fx_executions`, `ust_trades`, `live_prices`).

### 4. Run everything

```bash
scripts/start-all.sh      # Linux / macOS / Git Bash
scripts\start-all.bat     # Windows — each process gets its own titled cmd window
```

This launches:
1. Simulated WS feed (`:9000`)
2. Simulated NATS publisher
3. Vortex data server (`:8080`)
4. Admin GUI (`:8090`)

### 5. Verify

- **Data server health:** http://localhost:8080/health/ready
- **Live status dashboard:** http://localhost:8090/status
- **Admin CRUD:** http://localhost:8090/
- **Prometheus metrics:** http://localhost:8080/metrics

Open a Perspective viewer in the browser and point it at `ws://localhost:8080/websocket` with `open_table("ust_trades")` — you should see the consumer count on the `/status` page increment in real time.

### Running individually

```bash
scripts/start-server.sh              # data server only
scripts/start-admin.sh               # admin GUI only
scripts/start-sim-ws-feed.sh         # WS feed simulator
scripts/start-sim-nats-publisher.sh  # NATS publisher simulator
```

---

## Configuration — env vars

Every setting reads from `VORTEX_*` environment variables via `pydantic-settings`. Nested config uses `__` as delimiter. See [`.env.example`](.env.example) for the definitive reference.

| Variable | Default | Purpose |
|---|---|---|
| `VORTEX_HOST` | `0.0.0.0` | Data server bind host |
| `VORTEX_PORT` | `8080` | Data server port |
| `VORTEX_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `VORTEX_LOG_FORMAT` | `auto` | `auto` / `json` / `console` |
| `VORTEX_SHUTDOWN_TIMEOUT` | `30.0` | Bounded graceful-shutdown seconds |
| `VORTEX_MONGO__URI` | `mongodb://localhost:27017/` | **Required in prod** |
| `VORTEX_MONGO__DATABASE` | `Vortex` | Mongo database name |
| `VORTEX_ADMIN__HOST` | `0.0.0.0` | Admin bind host |
| `VORTEX_ADMIN__PORT` | `8090` | Admin port |
| `VORTEX_ADMIN__SECRET_KEY` | dev default | **Rotate in prod** — Flask session key |
| `VORTEX_ADMIN__VORTEX_URL` | `http://localhost:8080` | Admin → data server URL |
| `VORTEX_ADMIN__VORTEX_STATUS_TIMEOUT` | `2.0` | Status proxy timeout (s) |

Transport connection details (NATS URL, Solace credentials, upstream WS URL) live in the Mongo `transports` collection, not env vars — edit them through the admin GUI.

---

## Admin GUI

Browse to `http://localhost:8090/`:

- **Dashboard** (`/`) — counts of configured transports and tables
- **Live Status** (`/status`) — auto-refreshes every 2s, shows:
  - Server version, uptime, shutdown state
  - Mongo reachability
  - Connected WebSocket clients
  - Per-transport `connected` / `restarts_total`
  - Per-table `row_count`, `consumers`, `msgs/sec`, total received/dropped, p50/p99 dispatch latency
- **Transports** (`/transports`) — CRUD for broker configs (type-specific fields)
- **Tables** (`/tables`) — CRUD for Perspective tables:
  - Schema editor (one `col: type` per line)
  - Transport binding
  - Topic / subject, durable consumer, index vs limit, NATS core-vs-jetstream mode

Changes take effect on the next `vortex-server` restart — no hot-reload.

---

## Observability

### Health probes

| Endpoint | Probe type | Returns |
|---|---|---|
| `GET /health/live` | Liveness | `200 {"status":"alive"}` unless shutting down |
| `GET /health/ready` | Readiness | `200` when Mongo reachable + ≥1 connector up; `503` with `problems[]` otherwise |
| `GET /health` | (alias for `/health/ready`) | — |

### Prometheus metrics (`GET /metrics`)

| Metric | Type | Labels |
|---|---|---|
| `vortex_messages_received_total` | Counter | transport, table |
| `vortex_messages_dropped_total` | Counter | transport, reason |
| `vortex_message_dispatch_seconds` | Histogram | table |
| `vortex_connector_up` | Gauge | transport, type |
| `vortex_connector_restarts_total` | Counter | transport, type |
| `vortex_tables_registered` | Gauge | — |
| `vortex_mongo_reachable` | Gauge | — |
| `vortex_websocket_clients` | Gauge | — |
| `vortex_table_consumers` | Gauge | table |
| `vortex_shutting_down` | Gauge | — |
| `vortex_server_info` | Gauge | version |

### Structured logging

Every log line is a structured event with a `cid` correlation ID, bound transport/table context, and JSON output in production (console for `LOG_LEVEL=DEBUG`). Third-party libs (`nats.aio`, `pymongo`, `tornado`) funnel through the same processor chain.

---

## Data model

Configuration lives in MongoDB (database: `Vortex`).

### `transports` collection

```json
{
  "name": "nats-monty",
  "type": "nats",
  "enabled": true,
  "config": { "url": "nats://host:4222", "user": null, "password": null }
}
```

Types: `nats`, `solace`, `ws`. Each has its own `config` shape — see `vortex/admin/app.py:20`.

### `tables` collection

```json
{
  "name": "ust_trades",
  "transport_name": "nats-monty",
  "topic": "rates.ust.trades.>",
  "nats_mode": "core",
  "durable": null,
  "index": "trade_id",
  "limit": null,
  "schema": {
    "trade_id": "string",
    "qty": "float",
    "ts": "datetime"
  }
}
```

`index` is mutually exclusive with `limit`. `index` → upsert table (keyed); `limit` → rolling append window; neither → unbounded append.

`nats_mode` applies only to NATS transports: `core` (non-persistent, no broker setup) vs `jetstream` (requires a stream covering the subject; supports durable consumers).

---

## Development

### Run tests

```bash
.venv/Scripts/python -m pytest tests/ -v   # Windows
.venv/bin/python -m pytest tests/ -v       # Linux / macOS
```

Current suite: 17 tests covering registry, router, backoff, metrics, NATS dispatch, consumer tracking.

### Project layout

```
vortex/
├── server.py              # Data server entry point
├── registry.py            # TableRegistry (owns Perspective tables)
├── router.py              # UpdateRouter (payload → table.update)
├── status.py              # /api/status JSON handler
├── health.py              # Liveness / Readiness / Metrics handlers
├── perspective_handler.py # TrackedPerspectiveHandler (WS client counting)
├── config/
│   ├── settings.py        # pydantic-settings (env vars)
│   └── table_config.py    # TransportConfig, TableConfig dataclasses
├── connectors/
│   ├── base.py            # BaseConnector + supervisor pattern
│   ├── nats.py            # NATS (core + JetStream)
│   ├── solace.py          # Solace PubSub+
│   └── websocket_src.py   # Upstream WS client
├── store/
│   └── mongo.py           # MongoStore (transport + table repositories)
├── observability/
│   ├── logging.py         # structlog + stdlib bridge
│   ├── metrics.py         # Prometheus metric definitions
│   ├── correlation.py     # contextvar correlation IDs
│   └── backoff.py         # ExponentialBackoff with jitter
└── admin/
    ├── app.py             # Flask app factory + CRUD routes
    └── templates/         # Jinja templates
scripts/
├── install.{sh,bat}       # Create venv, pip install -e ".[dev]"
├── seed-mongo.{sh,bat}    # Upsert initial topology
├── start-server.{sh,bat}
├── start-admin.{sh,bat}
├── start-sim-ws-feed.{sh,bat}
├── start-sim-nats-publisher.{sh,bat}
├── start-all.{sh,bat}     # All-in-one launcher
├── seed_mongo.py          # Python seed module
├── sim_ws_feed.py         # Upstream WS simulator
└── sim_nats_publisher.py  # NATS trade publisher simulator
tests/
├── test_backoff.py
├── test_consumer_tracking.py
├── test_metrics.py
├── test_nats_connector.py
├── test_registry.py
└── test_router.py
```

---

## OpenShift / Kubernetes deployment

Two container images, separate deployments (different scaling & lifecycles):

- `Dockerfile` — data server on `:8080`
- `Dockerfile.admin` — Flask admin GUI on `:8090`

```bash
docker build -t vortex-server -f Dockerfile .
docker build -t vortex-admin  -f Dockerfile.admin .
```

### Env injection pattern

```yaml
# ConfigMap (non-secret)
apiVersion: v1
kind: ConfigMap
metadata:
  name: vortex-config
data:
  VORTEX_LOG_LEVEL: "INFO"
  VORTEX_LOG_FORMAT: "json"
  VORTEX_MONGO__DATABASE: "Vortex"
  VORTEX_ADMIN__VORTEX_URL: "http://vortex-server:8080"
---
# Secret (sensitive)
apiVersion: v1
kind: Secret
metadata:
  name: vortex-secrets
type: Opaque
stringData:
  VORTEX_MONGO__URI: "mongodb://user:pass@mongo-svc:27017/"
  VORTEX_ADMIN__SECRET_KEY: "random-production-key"
```

Mount both into each Deployment via `envFrom`:

```yaml
spec:
  containers:
    - name: vortex-server
      image: vortex-server:latest
      envFrom:
        - configMapRef:
            name: vortex-config
        - secretRef:
            name: vortex-secrets
      livenessProbe:
        httpGet: { path: /health/live,  port: 8080 }
      readinessProbe:
        httpGet: { path: /health/ready, port: 8080 }
```

### HAProxy / Ingress note

Perspective WebSocket connections are long-lived. Ensure `timeout tunnel` (HAProxy) or equivalent proxy timeout is set to **≥ 1 hour**, otherwise idle viewers will be disconnected.

---

## License

Internal — CapitalMarketsMacro.
