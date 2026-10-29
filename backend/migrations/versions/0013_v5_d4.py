"""v5.5 G5: D4 cause hypotheses, 5-Why links, experiments and causal decisions (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0013_v5_d4"
down_revision = "0012_preflight_review_policy"
branch_labels = None
depends_on = None

TABLES = ('cause_hypotheses', 'why_links', 'experiments', 'causal_decisions')


def upgrade() -> None:
    op.create_table('cause_hypotheses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('cause_type', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('counter_evidence_ids', sa.JSON(), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('source_claim', sa.String(length=40), nullable=True),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cause_hypotheses_case_id'), 'cause_hypotheses', ['case_id'], unique=False)
    op.create_table('causal_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('hypothesis_id', sa.Integer(), nullable=False),
    sa.Column('decision', sa.String(length=14), nullable=False),
    sa.Column('basis_experiment_ids', sa.JSON(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['hypothesis_id'], ['cause_hypotheses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_causal_decisions_case_id'), 'causal_decisions', ['case_id'], unique=False)
    op.create_index(op.f('ix_causal_decisions_hypothesis_id'), 'causal_decisions', ['hypothesis_id'], unique=False)
    op.create_table('experiments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('hypothesis_id', sa.Integer(), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('controlled_conditions', sa.JSON(), nullable=False),
    sa.Column('baseline', sa.JSON(), nullable=False),
    sa.Column('intervention', sa.JSON(), nullable=False),
    sa.Column('sample_size', sa.Integer(), nullable=False),
    sa.Column('acceptance_rule', sa.Text(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('result', sa.String(length=14), nullable=False),
    sa.Column('synthetic', sa.Boolean(), nullable=False),
    sa.Column('performed_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['hypothesis_id'], ['cause_hypotheses.id'], ),
    sa.ForeignKeyConstraint(['performed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiments_case_id'), 'experiments', ['case_id'], unique=False)
    op.create_index(op.f('ix_experiments_hypothesis_id'), 'experiments', ['hypothesis_id'], unique=False)
    op.create_table('why_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=False),
    sa.Column('child_id', sa.Integer(), nullable=False),
    sa.Column('supporting_ids', sa.JSON(), nullable=False),
    sa.Column('falsification_criteria', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['child_id'], ['cause_hypotheses.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['cause_hypotheses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_why_links_case_id'), 'why_links', ['case_id'], unique=False)
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_table('why_links')
    op.drop_table('experiments')
    op.drop_table('causal_decisions')
    op.drop_table('cause_hypotheses')
