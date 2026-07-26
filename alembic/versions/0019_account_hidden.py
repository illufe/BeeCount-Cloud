"""Add account hidden flag.

Revision ID: 0019_account_hidden
Revises: 0018_tx_multi_currency
"""

import sqlalchemy as sa
from alembic import op


revision = "0019_account_hidden"
down_revision = "0018_tx_multi_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_account_projection",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("user_account_projection", "hidden")
