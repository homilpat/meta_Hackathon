"""IN2: parsed document elements per file and versioned intake drafts (both append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0019_intake_drafts"
down_revision = "0018_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('intake_parses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('parser_version', sa.String(length=30), nullable=False),
    sa.Column('elements', sa.JSON(), nullable=False),
    sa.Column('coverage', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['intake_files.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_id', 'parser_version')
    )
    op.create_index('ix_intake_parses_file_id', 'intake_parses', ['file_id'])
    op.create_table('intake_extractions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('mode', sa.String(length=12), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('model', sa.String(length=60), nullable=True),
    sa.Column('prompt_version', sa.String(length=20), nullable=True),
    sa.Column('parser_version', sa.String(length=30), nullable=False),
    sa.Column('draft', sa.JSON(), nullable=False),
    sa.Column('raw', sa.JSON(), nullable=True),
    sa.Column('withheld', sa.JSON(), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('intake_id', 'version')
    )
    op.create_index('ix_intake_extractions_intake_id', 'intake_extractions', ['intake_id'])
    for table in ("intake_parses", "intake_extractions"):
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_index('ix_intake_extractions_intake_id', table_name='intake_extractions')
    op.drop_table('intake_extractions')
    op.drop_index('ix_intake_parses_file_id', table_name='intake_parses')
    op.drop_table('intake_parses')
