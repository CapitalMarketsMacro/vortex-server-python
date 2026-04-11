from __future__ import annotations
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify

from vortex.config.settings import load_settings
from vortex.config.table_config import (
    TRANSPORT_TYPES,
    SCHEMA_TYPES,
    NATS_MODES,
)
from vortex.store.mongo import MongoStore

logger = logging.getLogger(__name__)


# ── Type-specific field lists ────────────────────────────────────────────────
# Each entry: (form_field_name, label, is_password)
TRANSPORT_FIELDS: dict[str, list[tuple[str, str, bool]]] = {
    "nats": [
        ("url", "Server URL (nats://host:port)", False),
        ("user", "Username (optional)", False),
        ("password", "Password (optional)", True),
        ("token", "Token (optional)", True),
    ],
    "solace": [
        ("host", "Host", False),
        ("port", "Port", False),
        ("vpn", "VPN name", False),
        ("username", "Username", False),
        ("password", "Password", True),
    ],
    "ws": [
        ("url", "Upstream WebSocket URL (ws://host:port/path)", False),
        ("reconnect_interval", "Reconnect interval (seconds)", False),
    ],
}


def _parse_schema_textarea(text: str) -> dict[str, str]:
    """
    Parse a textarea of 'col: type' lines into {col: type_string}.
    Unknown types fall back to 'string'.
    """
    schema: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"line {lineno}: expected 'col: type', got '{line}'")
        col, typ = line.split(":", 1)
        col = col.strip()
        typ = typ.strip().lower()
        if not col:
            raise ValueError(f"line {lineno}: empty column name")
        if typ not in SCHEMA_TYPES:
            raise ValueError(
                f"line {lineno}: unknown type '{typ}' (valid: {', '.join(SCHEMA_TYPES)})"
            )
        schema[col] = typ
    return schema


def _schema_to_textarea(schema: dict[str, str]) -> str:
    return "\n".join(f"{col}: {typ}" for col, typ in schema.items())


def create_app(store: MongoStore, secret_key: str = "dev") -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.secret_key = secret_key
    app.config["STORE"] = store

    @app.after_request
    def _cors(response):
        # Open CORS for the read-only API so the Perspective viewer (any origin)
        # can fetch the table list. The HTML pages set their own headers.
        if request.path.startswith("/api/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    # ── REST API (read-only) ───────────────────────────────────────────────
    @app.route("/api/tables", methods=["GET", "OPTIONS"])
    def api_tables():
        if request.method == "OPTIONS":
            return ("", 204)
        transports = {t["name"]: t for t in store.list_transports()}
        out = []
        for t in store.list_tables():
            tname = t.get("transport_name")
            transport_meta = transports.get(tname)
            out.append({
                "name": t["name"],
                "transport_name": tname,
                "transport_type": transport_meta["type"] if transport_meta else None,
                "transport_enabled": transport_meta["enabled"] if transport_meta else False,
                "topic": t.get("topic", ""),
                "nats_mode": t.get("nats_mode", "core"),
                "durable": t.get("durable"),
                "index": t.get("index"),
                "limit": t.get("limit"),
                "schema": t.get("schema", {}),
            })
        return jsonify({"tables": out})

    @app.route("/api/tables/<name>", methods=["GET", "OPTIONS"])
    def api_table(name):
        if request.method == "OPTIONS":
            return ("", 204)
        t = store.get_table(name)
        if t is None:
            return jsonify({"error": f"table '{name}' not found"}), 404
        transport_meta = store.get_transport(t.get("transport_name") or "")
        return jsonify({
            "name": t["name"],
            "transport_name": t.get("transport_name"),
            "transport_type": transport_meta["type"] if transport_meta else None,
            "transport_enabled": transport_meta["enabled"] if transport_meta else False,
            "topic": t.get("topic", ""),
            "nats_mode": t.get("nats_mode", "core"),
            "durable": t.get("durable"),
            "index": t.get("index"),
            "limit": t.get("limit"),
            "schema": t.get("schema", {}),
        })

    # ── Dashboard ──────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template(
            "index.html",
            transports=store.list_transports(),
            tables=store.list_tables(),
        )

    # ── Transports ─────────────────────────────────────────────────────────
    @app.route("/transports")
    def transports_list():
        return render_template("transports_list.html", transports=store.list_transports())

    @app.route("/transports/new", methods=["GET", "POST"])
    def transport_new():
        if request.method == "POST":
            return _handle_transport_form(None)
        return render_template(
            "transport_form.html",
            transport=None,
            transport_types=TRANSPORT_TYPES,
            fields_by_type=TRANSPORT_FIELDS,
            mode="new",
        )

    @app.route("/transports/<name>/edit", methods=["GET", "POST"])
    def transport_edit(name):
        existing = store.get_transport(name)
        if existing is None:
            abort(404)
        if request.method == "POST":
            return _handle_transport_form(name)
        return render_template(
            "transport_form.html",
            transport=existing,
            transport_types=TRANSPORT_TYPES,
            fields_by_type=TRANSPORT_FIELDS,
            mode="edit",
        )

    @app.route("/transports/<name>/delete", methods=["POST"])
    def transport_delete(name):
        bound = [t for t in store.list_tables() if t.get("transport_name") == name]
        if bound:
            flash(
                f"Cannot delete '{name}': {len(bound)} table(s) still reference it.",
                "error",
            )
            return redirect(url_for("transports_list"))
        store.delete_transport(name)
        flash(f"Transport '{name}' deleted.", "success")
        return redirect(url_for("transports_list"))

    def _handle_transport_form(original_name: str | None):
        f = request.form
        name = f.get("name", "").strip()
        ttype = f.get("type", "").strip()
        enabled = f.get("enabled") == "on"

        if not name:
            flash("Name is required.", "error")
            return redirect(request.url)
        if ttype not in TRANSPORT_TYPES:
            flash(f"Type must be one of {TRANSPORT_TYPES}.", "error")
            return redirect(request.url)

        config: dict = {}
        for field_name, _, _ in TRANSPORT_FIELDS[ttype]:
            val = f.get(f"config__{field_name}", "").strip()
            if val == "":
                continue
            # Numeric coercion for known numeric fields
            if field_name in ("port",):
                config[field_name] = int(val)
            elif field_name in ("reconnect_interval",):
                config[field_name] = float(val)
            else:
                config[field_name] = val

        doc = {"name": name, "type": ttype, "config": config, "enabled": enabled}

        if original_name and original_name != name:
            store.delete_transport(original_name)
        store.upsert_transport(doc)
        flash(f"Transport '{name}' saved.", "success")
        return redirect(url_for("transports_list"))

    # ── Tables ─────────────────────────────────────────────────────────────
    @app.route("/tables")
    def tables_list():
        return render_template("tables_list.html", tables=store.list_tables())

    @app.route("/tables/new", methods=["GET", "POST"])
    def table_new():
        if request.method == "POST":
            return _handle_table_form(None)
        return render_template(
            "table_form.html",
            table=None,
            transports=store.list_transports(),
            nats_modes=NATS_MODES,
            schema_text="",
            mode="new",
        )

    @app.route("/tables/<name>/edit", methods=["GET", "POST"])
    def table_edit(name):
        existing = store.get_table(name)
        if existing is None:
            abort(404)
        if request.method == "POST":
            return _handle_table_form(name)
        schema_text = _schema_to_textarea(existing.get("schema", {}))
        return render_template(
            "table_form.html",
            table=existing,
            transports=store.list_transports(),
            nats_modes=NATS_MODES,
            schema_text=schema_text,
            mode="edit",
        )

    @app.route("/tables/<name>/delete", methods=["POST"])
    def table_delete(name):
        store.delete_table(name)
        flash(f"Table '{name}' deleted.", "success")
        return redirect(url_for("tables_list"))

    def _handle_table_form(original_name: str | None):
        f = request.form
        name = f.get("name", "").strip()
        transport_name = f.get("transport_name", "").strip()
        topic = f.get("topic", "").strip()
        durable = f.get("durable", "").strip() or None
        index = f.get("index", "").strip() or None
        limit_raw = f.get("limit", "").strip()
        nats_mode = f.get("nats_mode", "core").strip()
        schema_raw = f.get("schema_text", "")

        if nats_mode not in NATS_MODES:
            flash(f"nats_mode must be one of {NATS_MODES}.", "error")
            return redirect(request.url)

        if not name:
            flash("Name is required.", "error")
            return redirect(request.url)
        if not transport_name:
            flash("Transport is required.", "error")
            return redirect(request.url)
        if store.get_transport(transport_name) is None:
            flash(f"Transport '{transport_name}' does not exist.", "error")
            return redirect(request.url)

        try:
            schema = _parse_schema_textarea(schema_raw)
        except ValueError as e:
            flash(f"Schema error: {e}", "error")
            return redirect(request.url)
        if not schema:
            flash("Schema cannot be empty.", "error")
            return redirect(request.url)

        limit: int | None = None
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                flash("Limit must be an integer.", "error")
                return redirect(request.url)

        if index and limit:
            flash("Set either index or limit, not both.", "error")
            return redirect(request.url)

        doc = {
            "name": name,
            "transport_name": transport_name,
            "topic": topic,
            "durable": durable,
            "index": index,
            "limit": limit,
            "nats_mode": nats_mode,
            "schema": schema,
        }

        if original_name and original_name != name:
            store.delete_table(original_name)
        store.upsert_table(doc)
        flash(f"Table '{name}' saved.", "success")
        return redirect(url_for("tables_list"))

    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    store = MongoStore(settings.mongo.uri, settings.mongo.database)
    app = create_app(store, secret_key=settings.admin.secret_key)
    logger.info(
        "vortex-admin running on http://%s:%d",
        settings.admin.host, settings.admin.port,
    )
    app.run(host=settings.admin.host, port=settings.admin.port, debug=False)


if __name__ == "__main__":
    run()
