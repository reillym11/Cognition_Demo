"""ap invoices: record every verifier for maker-checker exclusion

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ap_invoices",
        sa.Column(
            "touched_by",
            sa.ARRAY(sa.String(length=80)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.execute("UPDATE ap_invoices SET touched_by = ARRAY[verified_by] WHERE verified_by IS NOT NULL")
    op.alter_column("ap_invoices", "touched_by", server_default=None)


def downgrade() -> None:
    op.drop_column("ap_invoices", "touched_by")
