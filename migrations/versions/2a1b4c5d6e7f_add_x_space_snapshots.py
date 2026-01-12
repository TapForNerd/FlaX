"""add x space snapshots

Revision ID: 2a1b4c5d6e7f
Revises: 1f2b3c4d5e6f
Create Date: 2026-01-11 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a1b4c5d6e7f'
down_revision = '1f2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_space_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('space_id', sa.String(length=20), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=True),
        sa.Column('participant_count', sa.Integer(), nullable=True),
        sa.Column('subscriber_count', sa.Integer(), nullable=True),
        sa.Column('raw_space_data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['space_id'], ['x_spaces.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_space_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_space_snapshots_space_id'), ['space_id'], unique=False)


def downgrade():
    with op.batch_alter_table('x_space_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_space_snapshots_space_id'))

    op.drop_table('x_space_snapshots')
