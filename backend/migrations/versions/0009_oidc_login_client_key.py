"""foundation: per-client key on pending OIDC login states

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oidc_login_states",
        sa.Column("client_key", sa.String(length=64), nullable=False, server_default=""),
    )
    op.alter_column("oidc_login_states", "client_key", server_default=None)
    op.create_index(
        op.f("ix_oidc_login_states_client_key"), "oidc_login_states", ["client_key"], unique=False
    )
    op.create_index(
        op.f("ix_oidc_login_states_created_at"), "oidc_login_states", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oidc_login_states_created_at"), table_name="oidc_login_states")
    op.drop_index(op.f("ix_oidc_login_states_client_key"), table_name="oidc_login_states")
    op.drop_column("oidc_login_states", "client_key")
