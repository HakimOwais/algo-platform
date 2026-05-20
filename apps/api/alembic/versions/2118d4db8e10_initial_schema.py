"""initial_schema

Revision ID: 2118d4db8e10
Revises:
Create Date: 2026-05-20

Creates all eight application tables from scratch.  Intended to run against
an empty database; if tables already exist (created by create_all during
development), stamp the DB with this revision ID and subsequent migrations
will build on it incrementally.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

revision: str = "2118d4db8e10"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum types used in column definitions (create_type=False: we manage creation explicitly).
_side_col = PgEnum("BUY", "SELL", name="side", create_type=False)
_order_type_col = PgEnum("MARKET", "LIMIT", name="ordertype", create_type=False)
_order_status_col = PgEnum(
    "NEW", "SENT", "ACKED", "PARTIALLY_FILLED",
    "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "ERROR",
    name="orderstatus", create_type=False,
)

# Enum types used for create/drop (create_type=True is the default).
_side_enum = PgEnum("BUY", "SELL", name="side")
_order_type_enum = PgEnum("MARKET", "LIMIT", name="ordertype")
_order_status_enum = PgEnum(
    "NEW", "SENT", "ACKED", "PARTIALLY_FILLED",
    "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "ERROR",
    name="orderstatus",
)


def upgrade() -> None:
    bind = op.get_bind()

    # Idempotency guard: if the schema was already created by create_all (before
    # Alembic was introduced), skip all DDL.  Alembic will record this revision
    # in alembic_version so future migrations apply normally.
    from sqlalchemy import inspect as sa_inspect
    if "instruments" in sa_inspect(bind).get_table_names():
        return

    _side_enum.create(bind, checkfirst=True)
    _order_type_enum.create(bind, checkfirst=True)
    _order_status_enum.create(bind, checkfirst=True)

    # ── instruments ───────────────────────────────────────────────────────────
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False, server_default="NSE"),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("tick_size", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "exchange", name="uq_symbol_exchange"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])

    # ── orders ────────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", _side_col, nullable=False),
        sa.Column("order_type", _order_type_col, nullable=False, server_default="MARKET"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("status", _order_status_col, nullable=False, server_default="NEW"),
        sa.Column("broker_order_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("rejection_reason", sa.String(512), nullable=True),
        sa.Column("is_paper", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )
    op.create_index("ix_orders_strategy_name", "orders", ["strategy_name"])
    op.create_index("ix_orders_symbol", "orders", ["symbol"])
    op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])
    op.create_index("ix_orders_idempotency_key", "orders", ["idempotency_key"])

    # ── fills ─────────────────────────────────────────────────────────────────
    op.create_table(
        "fills",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_fills_order_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fills_order_id", "fills", ["order_id"])
    op.create_index("ix_fills_symbol", "fills", ["symbol"])
    op.create_index("ix_fills_filled_at", "fills", ["filled_at"])

    # ── positions ─────────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_positions_symbol"),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"])

    # ── bars ──────────────────────────────────────────────────────────────────
    op.create_table(
        "bars",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False, server_default="1m"),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_bars_instrument_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bars_instrument_id", "bars", ["instrument_id"])
    op.create_index("ix_bars_timestamp", "bars", ["timestamp"])
    op.create_index(
        "ix_bars_instrument_ts_interval",
        "bars",
        ["instrument_id", "timestamp", "interval"],
    )

    # ── strategy_configs ──────────────────────────────────────────────────────
    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="PAPER"),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_strategy_configs_name"),
    )
    op.create_index("ix_strategy_configs_name", "strategy_configs", ["name"])

    # ── decision_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "decision_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("signal", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_logs_strategy_name", "decision_logs", ["strategy_name"])
    op.create_index("ix_decision_logs_symbol", "decision_logs", ["symbol"])
    op.create_index("ix_decision_logs_created_at", "decision_logs", ["created_at"])

    # ── risk_events ───────────────────────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_events_event_type", "risk_events", ["event_type"])
    op.create_index("ix_risk_events_created_at", "risk_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("risk_events")
    op.drop_table("decision_logs")
    op.drop_table("strategy_configs")
    op.drop_table("bars")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("instruments")

    bind = op.get_bind()
    _order_status_enum.drop(bind, checkfirst=True)
    _order_type_enum.drop(bind, checkfirst=True)
    _side_enum.drop(bind, checkfirst=True)
