"""Gapless sequential numbers for user-facing display (order #, invoice #,
customer #) — kept entirely separate from the database primary keys those
records also have.

Primary keys (Order.id, User.id, ...) must never be renumbered or reused:
JWTs embed user.id, every foreign key in the schema points at these exact
values, and MySQL's own AUTO_INCREMENT already guarantees they're unique
forever. But AUTO_INCREMENT also never fills in a gap left by a deleted row
or a rolled-back transaction, which is why raw ids "jump around" over time.

A Sequence row is a plain counter that only advances when explicitly bumped,
inside the same transaction as the row being created — so if that transaction
rolls back, the bump rolls back with it, and the number is never handed out.
"""
from sqlalchemy.orm import Session

from ..models import Sequence


def next_sequence_value(db: Session, name: str) -> int:
    """Atomically increment and return the next value for `name`.

    Must be called before the caller's own db.commit() — the row lock taken
    here (via the UPDATE below) is what serializes concurrent requests onto
    the same counter, and rolling back the caller's transaction rolls this
    increment back too.
    """
    seq = db.get(Sequence, name, with_for_update=True)
    if seq is None:
        seq = Sequence(name=name, value=0)
        db.add(seq)
        db.flush()
        seq = db.get(Sequence, name, with_for_update=True)
    seq.value += 1
    db.flush()
    return seq.value
