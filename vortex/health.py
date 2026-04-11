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
