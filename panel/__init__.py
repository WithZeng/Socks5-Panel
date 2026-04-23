import os
from pathlib import Path

from flask import Flask
from sqlalchemy import inspect, text

from .config import Config
from .models import ZeroPreset, db
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
        ensure_zero_presets()

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

    batch_columns = {column["name"] for column in inspector.get_columns("conversion_batches")}
    if "preset_snapshot_json" not in batch_columns:
        statements.append("ALTER TABLE conversion_batches ADD COLUMN preset_snapshot_json TEXT DEFAULT ''")

    for statement in statements:
        db.session.execute(text(statement))

    if statements:
        db.session.commit()


def ensure_zero_presets() -> None:
    presets = [
        {
            "name": "基础直连-ICMP",
            "description": "不走转发链，使用 ICMP 测试，适合基础可用性验证。",
            "config": {
                "chain_mode": False,
                "forward_endpoints": [],
                "forward_chain_smart_select": True,
                "forward_chain_fixed_hops_num": 0,
                "forward_chain_fixed_last_hops_num": 0,
                "balance_strategy": 0,
                "target_select_mode": 0,
                "test_method": 1,
                "enable_udp": True,
                "accept_proxy_protocol": False,
                "send_proxy_protocol_version": None,
                "custom_config": None,
                "tags": [],
            },
            "is_default": True,
        },
        {
            "name": "纯测试-TCP直连",
            "description": "不走转发链，使用 TCP 测试，适合排查基础连通问题。",
            "config": {
                "chain_mode": False,
                "forward_endpoints": [],
                "forward_chain_smart_select": True,
                "forward_chain_fixed_hops_num": 0,
                "forward_chain_fixed_last_hops_num": 0,
                "balance_strategy": 0,
                "target_select_mode": 0,
                "test_method": 0,
                "enable_udp": True,
                "accept_proxy_protocol": False,
                "send_proxy_protocol_version": None,
                "custom_config": None,
                "tags": [],
            },
            "is_default": False,
        },
    ]

    changed = False
    for preset_data in presets:
        preset = ZeroPreset.query.filter_by(name=preset_data["name"]).first()
        if preset is None:
            preset = ZeroPreset(
                name=preset_data["name"],
                description=preset_data["description"],
                config_json=__import__("json").dumps(preset_data["config"], ensure_ascii=False),
                is_system=True,
                is_default=preset_data["is_default"],
            )
            db.session.add(preset)
            changed = True

    if changed:
        db.session.commit()
