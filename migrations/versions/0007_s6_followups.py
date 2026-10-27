"""S6: containment/RCA documents, evidence dependency graph, change impacts, append-only audit"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

APPEND_ONLY = ("approval_events", "workflow_events")  # frozen at this revision; later tables add their own
revision = "0007_s6"
down_revision = "0006_s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('change_impacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('asset_id', sa.String(length=120), nullable=False),
    sa.Column('supersedes_asset_id', sa.String(length=120), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('changed_evidence', sa.JSON(), nullable=False),
    sa.Column('impacted', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('evidence_dependencies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('src', sa.String(length=80), nullable=False),
    sa.Column('dst', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'src', 'dst')
    )
    with op.batch_alter_table('evidence_dependencies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evidence_dependencies_src'), ['src'], unique=False)

    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('based_on', sa.JSON(), server_default='[]', nullable=False))
        batch_op.alter_column('doc_type',
           existing_type=sa.VARCHAR(length=10),
           type_=sa.String(length=20),
           existing_nullable=False)
        batch_op.alter_column('status',
           existing_type=sa.VARCHAR(length=20),
           type_=sa.String(length=24),
           existing_nullable=False)

    for table in APPEND_ONLY:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    for table in APPEND_ONLY:
        for op_name in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{op_name}")
    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.alter_column('status',
           existing_type=sa.String(length=24),
           type_=sa.VARCHAR(length=20),
           existing_nullable=False)
        batch_op.alter_column('doc_type',
           existing_type=sa.String(length=20),
           type_=sa.VARCHAR(length=10),
           existing_nullable=False)
        batch_op.drop_column('based_on')

    with op.batch_alter_table('evidence_dependencies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evidence_dependencies_src'))

    op.drop_table('evidence_dependencies')
    op.drop_table('change_impacts')
