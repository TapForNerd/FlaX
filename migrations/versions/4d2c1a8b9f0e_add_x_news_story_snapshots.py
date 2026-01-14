"""add x news story snapshots

Revision ID: 4d2c1a8b9f0e
Revises: 3b7a9c2d4e5f
Create Date: 2026-01-12 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4d2c1a8b9f0e'
down_revision = '3b7a9c2d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_news_story_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('news_id', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=500), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('hook', sa.Text(), nullable=True),
        sa.Column('disclaimer', sa.Text(), nullable=True),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_news_data', sa.JSON(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_news_story_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_news_story_snapshots_news_id'), ['news_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_x_news_story_snapshots_source'), ['source'], unique=False)


def downgrade():
    with op.batch_alter_table('x_news_story_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_news_story_snapshots_source'))
        batch_op.drop_index(batch_op.f('ix_x_news_story_snapshots_news_id'))

    op.drop_table('x_news_story_snapshots')
