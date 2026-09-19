"""Add indexes the incremental column upgrades never created

Columns added after a table already existed came in through
schema_upgrade.py's `ALTER TABLE ... ADD COLUMN`, which creates the column
but not the index the model declares — so `notifications.type`,
`notifications.order_id`, `development_emails.status` and
`development_emails.notification_type` were unindexed in databases that
predate them. Filtering the inbox or the email log scanned the whole table.

The unique indexes on `orders.order_number` and `users.customer_number` are
also renamed to the names SQLAlchemy generates (MySQL had auto-named them
after the column), so the live schema matches the models exactly and
`alembic check` stays clean.

Every step checks the live schema first, so this is safe on a database
created from 0001 (where the indexes already exist) and on one upgraded
in place.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index name, table, columns, unique, replaces)
INDEXES = [
    ("ix_notifications_type", "notifications", ["type"], False, None),
    ("ix_notifications_order_id", "notifications", ["order_id"], False, None),
    ("ix_development_emails_status", "development_emails", ["status"], False, None),
    ("ix_development_emails_notification_type", "development_emails", ["notification_type"], False, None),
    ("ix_orders_order_number", "orders", ["order_number"], True, "order_number"),
    ("ix_users_customer_number", "users", ["customer_number"], True, "customer_number"),
]


def _existing(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    for name, table, columns, unique, replaces in INDEXES:
        existing = _existing(table)
        if name in existing:
            continue
        if replaces and replaces in existing:
            # MySQL won't allow two unique indexes over the same column with
            # different names, so drop the auto-named one first.
            op.drop_index(replaces, table_name=table)
        op.create_index(name, table, columns, unique=unique)


def downgrade() -> None:
    for name, table, columns, unique, replaces in INDEXES:
        existing = _existing(table)
        if name not in existing:
            continue
        op.drop_index(name, table_name=table)
        if replaces:
            op.create_index(replaces, table, columns, unique=unique)
