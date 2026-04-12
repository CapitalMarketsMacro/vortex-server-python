from __future__ import annotations
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY

# Use the default global registry — Prometheus exporters scrape this directly.
# Tests that need isolation can pass their own registry to the metric constructors.

NAMESPACE = "vortex"


# ── Inbound message flow ─────────────────────────────────────────────────────

MESSAGES_RECEIVED = Counter(
    f"{NAMESPACE}_messages_received_total",
    "Inbound messages received from a transport, broken down by table.",
    ["transport", "table"],
)

MESSAGES_DROPPED = Counter(
    f"{NAMESPACE}_messages_dropped_total",
    "Inbound messages that could not be dispatched (parse error, unknown table, update failure).",
    ["transport", "reason"],
)

MESSAGE_DISPATCH_SECONDS = Histogram(
    f"{NAMESPACE}_message_dispatch_seconds",
    "End-to-end time from receiving a message to applying it to a Perspective table.",
    ["table"],
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


# ── Connector health ─────────────────────────────────────────────────────────

CONNECTOR_UP = Gauge(
    f"{NAMESPACE}_connector_up",
    "1 if the connector currently considers itself connected, 0 otherwise.",
    ["transport", "type"],
)

CONNECTOR_RESTARTS = Counter(
    f"{NAMESPACE}_connector_restarts_total",
    "Number of times a connector's supervisor loop entered the reconnect path.",
    ["transport", "type"],
)


# ── Registry / table health ──────────────────────────────────────────────────

TABLES_REGISTERED = Gauge(
    f"{NAMESPACE}_tables_registered",
    "Number of Perspective tables currently registered in the local TableRegistry.",
)


# ── Mongo store ──────────────────────────────────────────────────────────────

MONGO_REACHABLE = Gauge(
    f"{NAMESPACE}_mongo_reachable",
    "1 if the configured MongoDB instance responded to the last ping, 0 otherwise.",
)


# ── Process state ────────────────────────────────────────────────────────────

SERVER_INFO = Gauge(
    f"{NAMESPACE}_server_info",
    "Static server metadata, value always 1.",
    ["version"],
)

SHUTTING_DOWN = Gauge(
    f"{NAMESPACE}_shutting_down",
    "1 once a graceful shutdown has begun, 0 otherwise. Liveness checks read this.",
)


__all__ = [
    "REGISTRY",
    "MESSAGES_RECEIVED",
    "MESSAGES_DROPPED",
    "MESSAGE_DISPATCH_SECONDS",
    "CONNECTOR_UP",
    "CONNECTOR_RESTARTS",
    "TABLES_REGISTERED",
    "MONGO_REACHABLE",
    "SERVER_INFO",
    "SHUTTING_DOWN",
]
