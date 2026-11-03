"""Person-confirmed inspection XLSX imports into a case (spec §28, XLS-IN-01..05)"""

import sqlalchemy as sa
from alembic import op

revision = "0028_inspection_imports"
down_revision = "0027_agent_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('inspection_imports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('sheet', sa.String(length=120), nullable=False),
    sa.Column('header_row', sa.Integer(), nullable=False),
    sa.Column('mapping', sa.JSON(), nullable=False),
    sa.Column('mapping_version', sa.String(length=20), nullable=False),
    sa.Column('included_rows', sa.JSON(), nullable=False),
    sa.Column('excluded', sa.JSON(), nullable=False),
    sa.Column('rows', sa.JSON(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('supersedes_id', sa.Integer(), nullable=True),
    sa.Column('signature', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['file_id'], ['intake_files.id'], ),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signature')
    )
    op.create_index(op.f('ix_inspection_imports_case_id'), 'inspection_imports', ['case_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_inspection_imports_case_id'), table_name='inspection_imports')
    op.drop_table('inspection_imports')
