"""v5.5 G8: template contracts, validation runs, experience memory entries/retrievals/decisions (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0016_v5_g8"
down_revision = "0015_v5_d7_d8"
branch_labels = None
depends_on = None

TABLES = ('template_contracts', 'validation_runs', 'experience_entries', 'experience_retrievals', 'recommendation_decisions')


def upgrade() -> None:
    op.create_table('experience_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('entry_key', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=80), nullable=False),
    sa.Column('site', sa.String(length=40), nullable=False),
    sa.Column('process_type', sa.String(length=40), nullable=False),
    sa.Column('acl_roles', sa.JSON(), nullable=False),
    sa.Column('symptom_text', sa.Text(), nullable=False),
    sa.Column('features', sa.JSON(), nullable=False),
    sa.Column('cause_text', sa.Text(), nullable=False),
    sa.Column('cause_status', sa.String(length=10), nullable=False),
    sa.Column('action_code', sa.String(length=40), nullable=False),
    sa.Column('action_text', sa.Text(), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('outcome_evidence', sa.JSON(), nullable=False),
    sa.Column('recurrence', sa.String(length=20), nullable=False),
    sa.Column('recurrence_note', sa.Text(), nullable=False),
    sa.Column('applicability', sa.JSON(), nullable=False),
    sa.Column('field_checks', sa.JSON(), nullable=False),
    sa.Column('available_at', sa.String(length=40), nullable=False),
    sa.Column('bank_eligibility', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('source_sha256', sa.String(length=64), nullable=False),
    sa.Column('indexed_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entry_key', 'version')
    )
    op.create_index(op.f('ix_experience_entries_entry_key'), 'experience_entries', ['entry_key'], unique=False)
    op.create_table('template_contracts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contract_id', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('customer', sa.String(length=60), nullable=False),
    sa.Column('site', sa.String(length=40), nullable=False),
    sa.Column('process_type', sa.String(length=40), nullable=False),
    sa.Column('doc_types', sa.JSON(), nullable=False),
    sa.Column('effective_from', sa.String(length=40), nullable=False),
    sa.Column('effective_to', sa.String(length=40), nullable=True),
    sa.Column('template_doc', sa.String(length=60), nullable=False),
    sa.Column('rules', sa.JSON(), nullable=False),
    sa.Column('contract_hash', sa.String(length=64), nullable=False),
    sa.Column('authorized_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('experience_retrievals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('query_text', sa.Text(), nullable=False),
    sa.Column('query_sha256', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=24), nullable=False),
    sa.Column('results', sa.JSON(), nullable=False),
    sa.Column('method_version', sa.String(length=120), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_retrievals_case_id'), 'experience_retrievals', ['case_id'], unique=False)
    op.create_table('recommendation_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('retrieval_id', sa.Integer(), nullable=False),
    sa.Column('entry_key', sa.String(length=80), nullable=False),
    sa.Column('entry_version', sa.Integer(), nullable=False),
    sa.Column('entry_sha256', sa.String(length=64), nullable=False),
    sa.Column('case_snapshot_sha256', sa.String(length=64), nullable=False),
    sa.Column('decision', sa.String(length=24), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['retrieval_id'], ['experience_retrievals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recommendation_decisions_case_id'), 'recommendation_decisions', ['case_id'], unique=False)
    op.create_table('validation_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('document_version_id', sa.Integer(), nullable=False),
    sa.Column('document_sha256', sa.String(length=64), nullable=False),
    sa.Column('evidence_sha256', sa.String(length=64), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('template_hash', sa.String(length=64), nullable=True),
    sa.Column('contract_ref', sa.String(length=60), nullable=True),
    sa.Column('rules_version', sa.String(length=30), nullable=False),
    sa.Column('result', sa.String(length=8), nullable=False),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('predicates', sa.JSON(), nullable=False),
    sa.Column('validated_by', sa.String(length=40), nullable=False),
    sa.Column('validated_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['validated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_validation_runs_case_id'), 'validation_runs', ['case_id'], unique=False)
    op.create_index(op.f('ix_validation_runs_document_version_id'), 'validation_runs', ['document_version_id'], unique=False)
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_table('validation_runs')
    op.drop_table('recommendation_decisions')
    op.drop_table('experience_retrievals')
    op.drop_table('template_contracts')
    op.drop_table('experience_entries')
