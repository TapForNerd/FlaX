"""add x media uploads

Revision ID: 5c4d3e2f1a0b
Revises: 4d2c1a8b9f0e
Create Date: 2026-01-12 11:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c4d3e2f1a0b'
down_revision = '4d2c1a8b9f0e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'x_media_uploads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('x_user_id', sa.String(length=64), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=True),
        sa.Column('content_type', sa.String(length=120), nullable=True),
        sa.Column('media_category', sa.String(length=40), nullable=True),
        sa.Column('media_type', sa.String(length=60), nullable=True),
        sa.Column('output_format', sa.String(length=20), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('stored_size', sa.Integer(), nullable=True),
        sa.Column('upload_mode', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('media_id', sa.String(length=32), nullable=True),
        sa.Column('media_key', sa.String(length=64), nullable=True),
        sa.Column('raw_response', sa.JSON(), nullable=True),
        sa.Column('file_blob', sa.LargeBinary(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('x_media_uploads', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_x_media_uploads_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('x_media_uploads', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_x_media_uploads_user_id'))

    op.drop_table('x_media_uploads')
