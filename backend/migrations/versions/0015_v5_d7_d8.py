"""v5.5 G7: controlled-document registry, D7 prevention deployments, D8 acknowledgements and closures (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0015_v5_d7_d8"
down_revision = "0014_v5_d5_d6"
branch_labels = None
depends_on = None

TABLES = ('controlled_documents', 'prevention_deployments', 'closure_acks', 'closures')


def upgrade() -> None:
    op.create_table('closure_acks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('responsibility', sa.String(length=20), nullable=False),
    sa.Column('contribution', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_closure_acks_case_id'), 'closure_acks', ['case_id'], unique=False)
    op.create_table('closures',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('snapshot_sha256', sa.String(length=64), nullable=False),
    sa.Column('residual_risks', sa.JSON(), nullable=False),
    sa.Column('customer_notification_ref', sa.String(length=120), nullable=True),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_closures_case_id'), 'closures', ['case_id'], unique=False)
    op.create_table('controlled_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('doc_number', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('site', sa.String(length=40), nullable=False),
    sa.Column('process_type', sa.String(length=40), nullable=False),
    sa.Column('customer', sa.String(length=60), nullable=False),
    sa.Column('effective_from', sa.String(length=40), nullable=False),
    sa.Column('effective_to', sa.String(length=40), nullable=True),
    sa.Column('acl_roles', sa.JSON(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('authored_by', sa.String(length=40), nullable=False),
    sa.Column('released_by', sa.String(length=40), nullable=True),
    sa.Column('case_id', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_controlled_documents_doc_number'), 'controlled_documents', ['doc_number'], unique=False)
    op.create_table('prevention_deployments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('doc_number', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('old_revision', sa.Integer(), nullable=False),
    sa.Column('new_revision', sa.Integer(), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('operators_in_scope', sa.JSON(), nullable=False),
    sa.Column('training', sa.JSON(), nullable=False),
    sa.Column('sister_lines', sa.JSON(), nullable=False),
    sa.Column('exceptions', sa.Text(), nullable=False),
    sa.Column('recorded_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prevention_deployments_case_id'), 'prevention_deployments', ['case_id'], unique=False)
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_table('prevention_deployments')
    op.drop_table('controlled_documents')
    op.drop_table('closures')
    op.drop_table('closure_acks')
