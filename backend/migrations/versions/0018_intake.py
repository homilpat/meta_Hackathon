"""IN1: customer-document intake records (mutable header) and their original files (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0018_intake"
down_revision = "0017_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('intake_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.String(length=40), nullable=False),
    sa.Column('idem_key', sa.String(length=80), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'idem_key')
    )
    op.create_table('intake_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('media_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('data_origin', sa.String(length=20), nullable=False),
    sa.Column('checks', sa.JSON(), nullable=False),
    sa.Column('uploaded_by', sa.String(length=40), nullable=False),
    sa.Column('uploaded_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_intake_files_intake_id', 'intake_files', ['intake_id'])
    for ddl in append_only_ddl("intake_files"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_index('ix_intake_files_intake_id', table_name='intake_files')
    op.drop_table('intake_files')
    op.drop_table('intake_records')
