from __future__ import annotations
import time
import json
import tornado.web
from prometheus_client import REGISTRY

from vortex.observability import get_logger

logger = get_logger(__name__)


def _sample(name: str, **labels) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


def _histogram_summary(name: str, **labels) -> dict:
    """
    Pull count, sum and bucket counts for a labelled histogram from the
    default registry. Returns {} if the metric isn't present yet.
    """
    out: dict = {}
    bucket_counts: list[tuple[float, float]] = []
    for fam in REGISTRY.collect():
        if fam.name != name:
            continue
        for sample in fam.samples:
            if not all(sample.labels.get(k) == v for k, v in labels.items()):
                continue
            sn = sample.name
            if sn.endswith("_bucket"):
                le = sample.labels.get("le")
                if le is not None:
                    try:
                        bucket_counts.append((float(le), sample.value))
                    except ValueError:
                        pass
            elif sn.endswith("_count"):
                out["count"] = sample.value
            elif sn.endswith("_sum"):
                out["sum"] = sample.value
    if bucket_counts and "count" in out and out["count"] > 0:
        # Approximate quantile from cumulative bucket counts
        bucket_counts.sort()
        total = out["count"]
        for q in (0.5, 0.95, 0.99):
            target = q * total
            for upper, cum in bucket_counts:
                if cum >= target:
                    out[f"p{int(q * 100)}_seconds"] = upper
                    break
    return out


class StatusHandler(tornado.web.RequestHandler):
    """
    GET /api/status — JSON snapshot of the running server.

    Designed to be polled by the admin GUI every 1–2 seconds. Counters
    are returned as raw cumulative values; the client computes rates by
    differencing successive samples.
    """

    def initialize(self, registry, store, connectors, start_time, version, shutdown_flag):
        self._registry = registry
        self._store = store
        self._connectors = connectors
        self._start_time = start_time
        self._version = version
        self._shutdown_flag = shutdown_flag

    def set_default_headers(self):
        # Open CORS for read-only metadata so any admin/dashboard can poll us
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    def get(self):
        try:
            self._store._client.admin.command("ping")
            mongo_ok = True
        except Exception:
            mongo_ok = False

        connector_by_name = {c.name: c for c in self._connectors}
        all_table_configs = list(self._registry._configs.values())

        # ── Transports ──────────────────────────────────────────────────────
        transports_out = []
        for c in self._connectors:
            transports_out.append({
                "name": c.name,
                "type": c.type,
                "connected": bool(c.is_up()),
                "restarts_total": _sample(
                    "vortex_connector_restarts_total",
                    transport=c.name, type=c.type,
                ) or 0.0,
                "tables": [
                    cfg.name for cfg in all_table_configs
                    if cfg.transport_name == c.name
                ],
            })

        # ── Tables ──────────────────────────────────────────────────────────
        tables_out = []
        for name, table in self._registry.all_tables().items():
            cfg = self._registry._configs.get(name)
            transport_name = cfg.transport_name if cfg else None
            connector = connector_by_name.get(transport_name) if transport_name else None
            try:
                row_count = int(table.size())
            except Exception as e:
                logger.warning("status.row_count_failed", table=name, error=str(e))
                row_count = None

            received = _sample(
                "vortex_messages_received_total",
                transport=transport_name or "", table=name,
            ) or 0.0
            dropped_unknown = _sample(
                "vortex_messages_dropped_total",
                transport=transport_name or "", reason="unknown_table",
            ) or 0.0
            dropped_err = _sample(
                "vortex_messages_dropped_total",
                transport=transport_name or "", reason="dispatch_error",
            ) or 0.0

            tables_out.append({
                "name": name,
                "transport_name": transport_name,
                "transport_connected": bool(connector and connector.is_up()),
                "row_count": row_count,
                "messages_received_total": received,
                "messages_dropped_total": dropped_unknown + dropped_err,
                "dispatch_latency": _histogram_summary(
                    "vortex_message_dispatch_seconds", table=name,
                ),
                "index": cfg.index if cfg else None,
                "limit": cfg.limit if cfg else None,
                "topic": cfg.topic if cfg else None,
                "nats_mode": cfg.nats_mode if cfg else None,
            })

        body = {
            "version": self._version,
            "uptime_seconds": round(time.monotonic() - self._start_time, 2),
            "shutting_down": self._shutdown_flag.is_set(),
            "mongo_reachable": mongo_ok,
            "timestamp": time.time(),
            "transports": transports_out,
            "tables": tables_out,
        }
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(body))
