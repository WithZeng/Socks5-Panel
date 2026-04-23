import os
from pathlib import Path

from flask import Flask
from sqlalchemy import inspect, text

from .config import Config
from .models import db
from .views import register_routes


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
        static_url_path="/static",
    )
    app.config.from_object(Config)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    register_routes(app)

    with app.app_context():
        db.create_all()
        ensure_compatible_schema()

    return app


def ensure_compatible_schema() -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "app_settings" not in tables:
        db.create_all()
        inspector = inspect(db.engine)

    relay_columns = {column["name"] for column in inspector.get_columns("relay_servers")}
    proxy_columns = {column["name"] for column in inspector.get_columns("proxy_records")}

    statements: list[str] = []
    if "zero_line_id" not in relay_columns:
        statements.append("ALTER TABLE relay_servers ADD COLUMN zero_line_id INTEGER")
    if "synced_at" not in relay_columns:
        statements.append("ALTER TABLE relay_servers ADD COLUMN synced_at DATETIME")
    if "raw_meta" not in relay_columns:
        statements.append("ALTER TABLE relay_servers ADD COLUMN raw_meta TEXT DEFAULT ''")
    if "zero_defaults_json" not in relay_columns:
        statements.append("ALTER TABLE relay_servers ADD COLUMN zero_defaults_json TEXT DEFAULT ''")
    if "zero_port_id" not in proxy_columns:
        statements.append("ALTER TABLE proxy_records ADD COLUMN zero_port_id INTEGER")
    if "zero_sync_status" not in proxy_columns:
        statements.append("ALTER TABLE proxy_records ADD COLUMN zero_sync_status VARCHAR(20) DEFAULT 'pending'")
    if "zero_sync_error" not in proxy_columns:
        statements.append("ALTER TABLE proxy_records ADD COLUMN zero_sync_error TEXT DEFAULT ''")
    if "reconcile_state" not in proxy_columns:
        statements.append("ALTER TABLE proxy_records ADD COLUMN reconcile_state VARCHAR(30) DEFAULT 'pending'")
    if "reconcile_note" not in proxy_columns:
        statements.append("ALTER TABLE proxy_records ADD COLUMN reconcile_note TEXT DEFAULT ''")

    for statement in statements:
        db.session.execute(text(statement))

    if statements:
        db.session.commit()
