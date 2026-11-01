"""MM: specialist vision tool requests with their input hashes (append-only); no model is connected"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0021_vision_requests"
down_revision = "0020_intake_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('vision_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=True),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('element_id', sa.String(length=60), nullable=False),
    sa.Column('image_sha256', sa.String(length=64), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('analysis_type', sa.String(length=30), nullable=False),
    sa.Column('reported_phenomenon', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['file_id'], ['intake_files.id'], ),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_vision_requests_intake_id', 'vision_requests', ['intake_id'])
    for ddl in append_only_ddl("vision_requests"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_index('ix_vision_requests_intake_id', table_name='vision_requests')
    op.drop_table('vision_requests')
