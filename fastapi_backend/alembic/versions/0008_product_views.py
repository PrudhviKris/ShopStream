"""Product views (recommendation engagement signal)

Adds the product_views table: one row per time a signed-in customer opens a
product's detail view. Feeds "Trending" and "Recommended for you" — see
app/services/recommendation_service.py.

user_id/product_id are plain indexed integers, not foreign keys — same
reasoning as Notification.order_id (see 0001/0003): a product with no order
history can still be hard-deleted, and that must never be blocked by its
view history.

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "product_views" not in _tables():
        op.create_table(
            "product_views",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("viewed_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_product_views_id", "product_views", ["id"])
        op.create_index("ix_product_views_user_id", "product_views", ["user_id"])
        op.create_index("ix_product_views_product_id", "product_views", ["product_id"])
        op.create_index("ix_product_views_viewed_at", "product_views", ["viewed_at"])


def downgrade() -> None:
    if "product_views" in _tables():
        op.drop_table("product_views")
