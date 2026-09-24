"""Gapless display numbers for payments and returns

Orders, invoices and customers already had a friendly "#N" that counts
1, 2, 3 with no gaps, kept separate from the primary key (which is an
AUTO_INCREMENT and leaves holes wherever a row was deleted). Payments and
return requests were the two departments still showing only the raw id.

Existing rows are numbered in the order they were created, so the oldest
payment becomes Payment #1, and the `sequences` counters are set to carry
on from there.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, index name, sequence name)
NUMBERED = [
    ("payments", "payment_number", "ix_payments_payment_number", "payment_number"),
    ("return_requests", "return_number", "ix_return_requests_return_number", "return_number"),
]


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    connection = op.get_bind()

    for table, column, index_name, sequence in NUMBERED:
        if column not in _columns(table):
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        if index_name not in _indexes(table):
            op.create_index(index_name, table, [column], unique=True)

        # Number what's already there, oldest first.
        rows = connection.execute(
            sa.text(f"SELECT id FROM {table} WHERE {column} IS NULL ORDER BY id")
        ).fetchall()
        start = connection.execute(
            sa.text(f"SELECT COALESCE(MAX({column}), 0) FROM {table}")
        ).scalar() or 0
        for offset, (row_id,) in enumerate(rows, start=1):
            connection.execute(
                sa.text(f"UPDATE {table} SET {column} = :n WHERE id = :id"),
                {"n": start + offset, "id": row_id},
            )

        # Point the shared counter at the highest number handed out, so new
        # rows continue the run instead of colliding with it.
        highest = connection.execute(
            sa.text(f"SELECT COALESCE(MAX({column}), 0) FROM {table}")
        ).scalar() or 0
        existing = connection.execute(
            sa.text("SELECT value FROM sequences WHERE name = :n"), {"n": sequence}
        ).scalar()
        if existing is None:
            connection.execute(
                sa.text("INSERT INTO sequences (name, value) VALUES (:n, :v)"),
                {"n": sequence, "v": highest},
            )
        elif existing < highest:
            connection.execute(
                sa.text("UPDATE sequences SET value = :v WHERE name = :n"),
                {"v": highest, "n": sequence},
            )


def downgrade() -> None:
    connection = op.get_bind()
    for table, column, index_name, sequence in NUMBERED:
        if index_name in _indexes(table):
            op.drop_index(index_name, table_name=table)
        if column in _columns(table):
            op.drop_column(table, column)
        connection.execute(sa.text("DELETE FROM sequences WHERE name = :n"), {"n": sequence})
