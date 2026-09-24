"""Returns and refunds

Adds the return_requests table, orders.delivered_at (the return window counts
from delivery), and the two new order statuses.

Autogenerate saw only part of this: AUTO_CREATE_SCHEMA had already created
return_requests in the development database, so the create_table below is
written by hand. The guard makes it safe on both kinds of database — one
created by create_all, and a fresh one built from migrations.

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = ("pending", "paid", "shipped", "delivered", "cancelled")
NEW_STATUSES = OLD_STATUSES + ("return_requested", "returned")


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "return_requests" not in _tables():
        op.create_table(
            "return_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(length=60), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("status", sa.Enum("pending", "approved", "rejected", name="returnstatus"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decided_by_id", sa.Integer(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("refund_amount", sa.Float(), nullable=True),
            sa.Column("refund_reference", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_return_requests_id", "return_requests", ["id"])
        op.create_index("ix_return_requests_order_id", "return_requests", ["order_id"])
        op.create_index("ix_return_requests_user_id", "return_requests", ["user_id"])
        op.create_index("ix_return_requests_status", "return_requests", ["status"])

    if "delivered_at" not in _columns("orders"):
        op.add_column("orders", sa.Column("delivered_at", sa.DateTime(), nullable=True))

    # Widen the status enum so 'return_requested' and 'returned' are storable.
    # MySQL only: SQLite keeps enums as plain text, and can't ALTER a column
    # type at all.
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "orders", "order_status",
            existing_type=mysql.ENUM(*OLD_STATUSES, collation="utf8mb4_unicode_ci"),
            type_=sa.Enum(*NEW_STATUSES, name="orderstatus"),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Orders mid-return have no equivalent in the old enum; park them back on
    # delivered so the narrowed column still accepts every row.
    op.execute(
        "UPDATE orders SET order_status = 'delivered' "
        "WHERE order_status IN ('return_requested', 'returned')"
    )
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "orders", "order_status",
            existing_type=sa.Enum(*NEW_STATUSES, name="orderstatus"),
            type_=mysql.ENUM(*OLD_STATUSES, collation="utf8mb4_unicode_ci"),
            existing_nullable=False,
        )
    if "delivered_at" in _columns("orders"):
        op.drop_column("orders", "delivered_at")
    if "return_requests" in _tables():
        op.drop_table("return_requests")
