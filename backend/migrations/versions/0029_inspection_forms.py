"""Company inspection XLSX forms registered by the AI operations department (append-only), and the form an
import was read with"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0029_inspection_forms"
down_revision = "0028_inspection_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('inspection_forms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('fields', sa.JSON(), nullable=False),
    sa.Column('required', sa.JSON(), nullable=False),
    sa.Column('header_search_rows', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_forms_name'), 'inspection_forms', ['name'], unique=False)
    for ddl in append_only_ddl("inspection_forms"):
        op.execute(ddl)
    with op.batch_alter_table('inspection_imports') as b:
        b.add_column(sa.Column('form', sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('inspection_imports') as b:
        b.drop_column('form')
    op.drop_index(op.f('ix_inspection_forms_name'), table_name='inspection_forms')
    op.drop_table('inspection_forms')
