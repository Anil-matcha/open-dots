"""add schedule failure tracking and task report tracking

Revision ID: 9f2a6e1c8b41
Revises: 7b3c9d1e4f20
Create Date: 2026-09-26 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f2a6e1c8b41'
down_revision: Union[str, Sequence[str], None] = '7b3c9d1e4f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'schedule',
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('schedule', sa.Column('paused_reason', sa.Text(), nullable=True))
    op.alter_column('schedule', 'consecutive_failures', server_default=None)

    op.add_column('task', sa.Column('reported_at', sa.DateTime(timezone=True), nullable=True))

    # Runs that finished before this feature existed would otherwise look
    # "unreported" and get backfilled as a flood of notifications the moment
    # the background job starts running.
    op.execute(
        """
        UPDATE task
        SET reported_at = updated_at
        WHERE schedule_id IS NOT NULL AND status IN ('succeeded', 'failed')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('task', 'reported_at')
    op.drop_column('schedule', 'paused_reason')
    op.drop_column('schedule', 'consecutive_failures')
