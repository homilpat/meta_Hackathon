"""v5 G2: versioned workflow policies, evidence quality assessments, process context and affected objects"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0010_v5_foundation"
down_revision = "0009_audit_chain"
branch_labels = None
depends_on = None

TABLES = ("workflow_policies", "evidence_quality", "process_contexts", "affected_objects")


def upgrade() -> None:
    op.create_table('workflow_policies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('policy_id', sa.String(length=60), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('applicability', sa.JSON(), nullable=False),
    sa.Column('body', sa.JSON(), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('effective_from', sa.String(length=40), nullable=False),
    sa.Column('approved_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('policy_id', 'version')
    )
    op.create_table('evidence_quality',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('evidence_id', sa.String(length=30), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('quality_state', sa.String(length=12), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('measurements', sa.JSON(), nullable=False),
    sa.Column('checked_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'evidence_id', 'version')
    )
    op.create_index('ix_evidence_quality_evidence_id', 'evidence_quality', ['evidence_id'])
    op.create_table('process_contexts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('site', sa.String(length=40), nullable=False),
    sa.Column('customer', sa.String(length=60), nullable=False),
    sa.Column('process_type', sa.String(length=40), nullable=False),
    sa.Column('adapter_version', sa.String(length=40), nullable=False),
    sa.Column('operation', sa.String(length=60), nullable=False),
    sa.Column('equipment', sa.JSON(), nullable=False),
    sa.Column('recipe', sa.String(length=60), nullable=True),
    sa.Column('config_hash', sa.String(length=64), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id')
    )
    op.create_table('affected_objects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('object_type', sa.String(length=30), nullable=False),
    sa.Column('object_id', sa.String(length=80), nullable=False),
    sa.Column('parent_id', sa.String(length=80), nullable=True),
    sa.Column('location', sa.String(length=60), nullable=True),
    sa.Column('shipment_state', sa.String(length=20), nullable=False),
    sa.Column('identity_source', sa.String(length=30), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_affected_objects_case_id', 'affected_objects', ['case_id'])
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
