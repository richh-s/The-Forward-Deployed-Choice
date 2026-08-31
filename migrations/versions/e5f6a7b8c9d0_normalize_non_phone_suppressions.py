"""Strip the phone-style '+' from non-phone suppression addresses.

Suppression addresses used to be normalised as either an email or a phone
number, with no third case. Telegram's address is a numeric chat id, so
normalize_phone prepended a '+': chat 555 was stored as '+555'. Reads
normalised identically, so opt-outs did work — but the stored data was wrong
on its face, and any lookup not going through suppression.py would miss.

normalize_address() now leaves non-phone channels alone. This rewrites the
rows written under the old rule, so an existing opt-out keeps matching. Without
it, someone who opted out of Telegram would start receiving messages again —
which is why this migration ships in the same change as the code.

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

# Channels whose address really is a phone number; everything else was
# mis-normalised. Kept literal rather than imported so the migration keeps
# describing this point in history even as the application code moves on.
PHONE_CHANNELS = ("sms", "whatsapp", "voice")
EMAIL_CHANNELS = ("email",)


def _rows(conn):
    return conn.execute(
        sa.text(
            "SELECT id, address FROM suppressions "
            "WHERE channel NOT IN :phone AND channel NOT IN :email "
            "AND address LIKE '+%'"
        ).bindparams(
            sa.bindparam("phone", PHONE_CHANNELS, expanding=True),
            sa.bindparam("email", EMAIL_CHANNELS, expanding=True),
        )
    ).fetchall()


def upgrade() -> None:
    conn = op.get_bind()
    for row_id, address in _rows(conn):
        rest = address[1:]
        # Only undo what normalize_phone would have done: it prepended '+'
        # solely when the value was all digits.
        if rest.isdigit():
            conn.execute(
                sa.text("UPDATE suppressions SET address = :a WHERE id = :i"),
                {"a": rest, "i": row_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, address FROM suppressions "
            "WHERE channel NOT IN :phone AND channel NOT IN :email"
        ).bindparams(
            sa.bindparam("phone", PHONE_CHANNELS, expanding=True),
            sa.bindparam("email", EMAIL_CHANNELS, expanding=True),
        )
    ).fetchall()
    for row_id, address in rows:
        if address.isdigit():
            conn.execute(
                sa.text("UPDATE suppressions SET address = :a WHERE id = :i"),
                {"a": "+" + address, "i": row_id},
            )
