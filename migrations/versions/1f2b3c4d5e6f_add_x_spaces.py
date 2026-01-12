"""add x spaces

Revision ID: 1f2b3c4d5e6f
Revises: 953560851be1
Create Date: 2026-01-11 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f2b3c4d5e6f'
down_revision = '953560851be1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_spaces',
        sa.Column('id', sa.String(length=20), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('creator_id', sa.BigInteger(), nullable=True),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('participant_count', sa.Integer(), nullable=True),
        sa.Column('subscriber_count', sa.Integer(), nullable=True),
        sa.Column('lang', sa.String(length=10), nullable=True),
        sa.Column('is_ticketed', sa.Boolean(), nullable=True),
        sa.Column('raw_space_data', sa.JSON(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['creator_id'], ['x_users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_spaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_spaces_creator_id'), ['creator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_x_spaces_state'), ['state'], unique=False)


def downgrade():
    with op.batch_alter_table('x_spaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_spaces_state'))
        batch_op.drop_index(batch_op.f('ix_x_spaces_creator_id'))

    op.drop_table('x_spaces')
