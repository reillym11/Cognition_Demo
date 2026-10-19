"""refunds: region on transactions for contractor row scope

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
        "refund_transactions",
        sa.Column("region", sa.String(length=4), nullable=False, server_default="US"),
    )
    # Same merchant-to-region mapping as app.tools.refunds.seed.merchant_region.
    op.execute(
        "UPDATE refund_transactions SET region = 'EU' "
        "WHERE split_part(merchant, ' ', 1) IN ('Contoso', 'Fabrikam')"
    )
    op.alter_column("refund_transactions", "region", server_default=None)
    op.create_index(op.f("ix_refund_transactions_region"), "refund_transactions", ["region"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refund_transactions_region"), table_name="refund_transactions")
    op.drop_column("refund_transactions", "region")
