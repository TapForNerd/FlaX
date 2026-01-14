"""add x usage snapshots

Revision ID: 6e7f8a9b0c1d
Revises: 5c4d3e2f1a0b
Create Date: 2026-01-12 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e7f8a9b0c1d'
down_revision = '5c4d3e2f1a0b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_usage_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('hours', sa.Integer(), nullable=True),
        sa.Column('cap_reset_day', sa.Integer(), nullable=True),
        sa.Column('project_cap', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.String(length=32), nullable=True),
        sa.Column('project_usage', sa.Integer(), nullable=True),
        sa.Column('daily_project_usage', sa.JSON(), nullable=True),
        sa.Column('daily_client_app_usage', sa.JSON(), nullable=True),
        sa.Column('raw_usage_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_usage_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_usage_snapshots_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('x_usage_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_usage_snapshots_user_id'))

    op.drop_table('x_usage_snapshots')
