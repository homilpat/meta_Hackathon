"""§29 AI-CFG-01/02: AI proposals of a column mapping for unregistered inspection XLSX (append-only), and the
confirmed mapping a person saved for one table structure, kept on the inspection form"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0030_inspection_mapping_proposals"
down_revision = "0029_inspection_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('inspection_mapping_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('sent', sa.JSON(), nullable=False),
    sa.Column('reply', sa.JSON(), nullable=True),
    sa.Column('proposal', sa.JSON(), nullable=True),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('usage', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_mapping_proposals_intake_id'), 'inspection_mapping_proposals', ['intake_id'],
                    unique=False)
    for ddl in append_only_ddl("inspection_mapping_proposals"):
        op.execute(ddl)
    # plain ADD COLUMN, not a batch copy: a copied table would lose its append-only triggers
    op.add_column('inspection_forms', sa.Column('source', sa.String(length=20), nullable=False,
                                                server_default="ADMIN"))
    op.add_column('inspection_forms', sa.Column('structure', sa.JSON(), nullable=True))
    op.add_column('inspection_forms', sa.Column('structure_sha', sa.String(length=64), nullable=True))
    op.add_column('inspection_forms', sa.Column('mapping', sa.JSON(), nullable=True))
    op.add_column('inspection_forms', sa.Column('proposal_id', sa.Integer(), nullable=True))
    op.add_column('inspection_forms', sa.Column('edits', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_inspection_forms_structure_sha'), 'inspection_forms', ['structure_sha'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_inspection_forms_structure_sha'), table_name='inspection_forms')
    with op.batch_alter_table('inspection_forms') as b:
        for c in ('edits', 'proposal_id', 'mapping', 'structure_sha', 'structure', 'source'):
            b.drop_column(c)
    op.drop_index(op.f('ix_inspection_mapping_proposals_intake_id'), table_name='inspection_mapping_proposals')
    op.drop_table('inspection_mapping_proposals')
