"""create schedule table, link tasks to schedules

Revision ID: 7b3c9d1e4f20
Revises: e2ee182c04a0
Create Date: 2026-09-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b3c9d1e4f20'
down_revision: Union[str, Sequence[str], None] = 'e2ee182c04a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('schedule',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('box_id', sa.String(), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('cron_expression', sa.String(), nullable=False),
    sa.Column('timezone', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_schedule_user_id'), 'schedule', ['user_id'], unique=False)
    op.create_index(op.f('ix_schedule_next_run_at'), 'schedule', ['next_run_at'], unique=False)

    op.add_column('task', sa.Column('schedule_id', sa.BigInteger(), nullable=True))
    op.add_column('task', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_task_schedule_id'), 'task', ['schedule_id'], unique=False)
    op.create_foreign_key('fk_task_schedule_id_schedule', 'task', 'schedule', ['schedule_id'], ['id'])
    op.create_unique_constraint('uq_task_schedule_id_scheduled_for', 'task', ['schedule_id', 'scheduled_for'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_task_schedule_id_scheduled_for', 'task', type_='unique')
    op.drop_constraint('fk_task_schedule_id_schedule', 'task', type_='foreignkey')
    op.drop_index(op.f('ix_task_schedule_id'), table_name='task')
    op.drop_column('task', 'scheduled_for')
    op.drop_column('task', 'schedule_id')

    op.drop_index(op.f('ix_schedule_next_run_at'), table_name='schedule')
    op.drop_index(op.f('ix_schedule_user_id'), table_name='schedule')
    op.drop_table('schedule')
