from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


class RelayServer(db.Model):
    __tablename__ = "relay_servers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    host = db.Column(db.String(255), nullable=False)
    port_range_start = db.Column(db.Integer, nullable=False)
    port_range_end = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    zero_line_id = db.Column(db.Integer, nullable=True, unique=True)
    synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    raw_meta = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=beijing_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
    )

    batches = db.relationship("ConversionBatch", back_populates="relay_server", lazy="dynamic")
    records = db.relationship("ProxyRecord", back_populates="relay_server", lazy="dynamic")


class ConversionBatch(db.Model):
    __tablename__ = "conversion_batches"

    id = db.Column(db.Integer, primary_key=True)
    batch_code = db.Column(db.String(40), nullable=False, unique=True, index=True)
    source_type = db.Column(db.String(20), nullable=False)
    relay_server_id = db.Column(db.Integer, db.ForeignKey("relay_servers.id"), nullable=False)
    relay_name = db.Column(db.String(120), nullable=False)
    relay_host = db.Column(db.String(255), nullable=False)
    port_range_start = db.Column(db.Integer, nullable=False)
    port_range_end = db.Column(db.Integer, nullable=False)
    assigned_start_port = db.Column(db.Integer, nullable=False)
    assigned_end_port = db.Column(db.Integer, nullable=False)
    country = db.Column(db.String(80), nullable=False, index=True)
    total_lines = db.Column(db.Integer, nullable=False, default=0)
    success_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    remark_prefix = db.Column(db.String(120), nullable=False, default="")
    raw_input = db.Column(db.Text, nullable=False)
    result_text = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    error_summary = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=beijing_now)

    relay_server = db.relationship("RelayServer", back_populates="batches")
    records = db.relationship(
        "ProxyRecord",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ProxyRecord.assigned_port",
    )


class ProxyRecord(db.Model):
    __tablename__ = "proxy_records"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("conversion_batches.id"), nullable=False)
    relay_server_id = db.Column(db.Integer, db.ForeignKey("relay_servers.id"), nullable=False)
    country = db.Column(db.String(80), nullable=False, index=True)
    remark = db.Column(db.String(200), nullable=False)
    origin_host = db.Column(db.String(255), nullable=False)
    origin_port = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(255), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    assigned_port = db.Column(db.Integer, nullable=False, index=True)
    zero_port_id = db.Column(db.Integer, nullable=True, unique=True)
    zero_sync_status = db.Column(db.String(20), nullable=False, default="pending")
    zero_sync_error = db.Column(db.Text, nullable=False, default="")
    forward_line = db.Column(db.Text, nullable=False)
    origin_line = db.Column(db.Text, nullable=False)
    json_entry = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=beijing_now)

    batch = db.relationship("ConversionBatch", back_populates="records")
    relay_server = db.relationship("RelayServer", back_populates="records")


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(120), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=beijing_now, onupdate=beijing_now)
