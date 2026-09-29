"""Reviews and ratings

Adds the reviews table: one row per (user, product) review, gated to
"pending" until staff approve or reject it.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "reviews" not in _tables():
        op.create_table(
            "reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("status", sa.Enum("pending", "approved", "rejected", name="reviewstatus"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
            sa.UniqueConstraint("user_id", "product_id", name="uq_review_user_product"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_reviews_id", "reviews", ["id"])
        op.create_index("ix_reviews_user_id", "reviews", ["user_id"])
        op.create_index("ix_reviews_product_id", "reviews", ["product_id"])
        op.create_index("ix_reviews_status", "reviews", ["status"])


def downgrade() -> None:
    if "reviews" in _tables():
        op.drop_table("reviews")
