"""add x trend snapshots

Revision ID: 3b7a9c2d4e5f
Revises: 2a1b4c5d6e7f
Create Date: 2026-01-12 09:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3b7a9c2d4e5f'
down_revision = '2a1b4c5d6e7f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_trend_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('woeid', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('trend_name', sa.String(length=255), nullable=False),
        sa.Column('tweet_count', sa.Integer(), nullable=True),
        sa.Column('post_count', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('trending_since', sa.String(length=80), nullable=True),
        sa.Column('raw_trend_data', sa.JSON(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_trend_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_trend_snapshots_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_x_trend_snapshots_trend_name'), ['trend_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_x_trend_snapshots_woeid'), ['woeid'], unique=False)


def downgrade():
    with op.batch_alter_table('x_trend_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_trend_snapshots_woeid'))
        batch_op.drop_index(batch_op.f('ix_x_trend_snapshots_trend_name'))
        batch_op.drop_index(batch_op.f('ix_x_trend_snapshots_source'))

    op.drop_table('x_trend_snapshots')
