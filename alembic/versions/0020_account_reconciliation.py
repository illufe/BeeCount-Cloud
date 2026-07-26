"""Add account responsibility and reconciliation metadata.

Revision ID: 0020_account_reconciliation
Revises: 0019_account_hidden
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_account_reconciliation"
down_revision = "0019_account_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_account_projection", sa.Column("responsible_user_id", sa.String(36), nullable=True))
    op.add_column("user_account_projection", sa.Column("reconciliation_month", sa.String(7), nullable=True))
    op.add_column("user_account_projection", sa.Column("reconciliation_status", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("user_account_projection", "reconciliation_status")
    op.drop_column("user_account_projection", "reconciliation_month")
    op.drop_column("user_account_projection", "responsible_user_id")
