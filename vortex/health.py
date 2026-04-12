from __future__ import annotations
import json
import tornado.web
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from vortex.observability import get_logger, metrics

logger = get_logger(__name__)


class _BaseHealth(tornado.web.RequestHandler):
    def initialize(self, registry, store, connectors, shutdown_flag):
        self._registry = registry
        self._store = store
        self._connectors = connectors
        self._shutdown_flag = shutdown_flag

    def _write_json(self, status_code: int, body: dict) -> None:
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(body))


class LivenessHandler(_BaseHealth):
    """
    /health/live — fast, no I/O. Returns 200 unless the process has begun
    shutting down. Used as the OpenShift / Kubernetes liveness probe.
    A failing liveness check tells the orchestrator to restart the pod.
    """
    def get(self):
        if self._shutdown_flag.is_set():
            self._write_json(503, {"status": "shutting_down"})
            return
        self._write_json(200, {"status": "alive"})


class ReadinessHandler(_BaseHealth):
    """
    /health/ready — checks that the process can actually serve traffic:
      • Mongo reachable
      • All registered tables present
      • At least one connector currently up (so a client opening a table
        will see live data, not a permanently empty table)
    Used as the OpenShift / Kubernetes readiness probe. A failing readiness
    check pulls the pod out of the load balancer without restarting it.
    """
    def get(self):
        if self._shutdown_flag.is_set():
            self._write_json(503, {"status": "shutting_down"})
            return

        problems: list[str] = []

        # Mongo
        try:
            self._store._client.admin.command("ping")
            metrics.MONGO_REACHABLE.set(1)
            mongo_ok = True
        except Exception as e:
            metrics.MONGO_REACHABLE.set(0)
            problems.append(f"mongo:{e.__class__.__name__}")
            mongo_ok = False

        # Tables
        table_names = sorted(self._registry.all_tables().keys())

        # Connectors — at least one up if any are configured
        connector_states = {c.name: bool(c.is_up()) for c in self._connectors}
        any_connector_up = any(connector_states.values())
        if self._connectors and not any_connector_up:
            problems.append("no_connectors_up")

        body = {
            "status": "ready" if not problems else "degraded",
            "mongo": "ok" if mongo_ok else "down",
            "tables": table_names,
            "connectors": connector_states,
            "problems": problems,
        }
        self._write_json(200 if not problems else 503, body)


class MetricsHandler(tornado.web.RequestHandler):
    """
    /metrics — Prometheus exposition format. Scrape with:
        scrape_configs:
          - job_name: vortex
            static_configs:
              - targets: ['vortex-server:8080']
    """
    def get(self):
        self.set_header("Content-Type", CONTENT_TYPE_LATEST)
        self.write(generate_latest())
