"""v5 G3: D0 triage, D1 team events, actions and append-only action events"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0011_v5_d0_d1"
down_revision = "0010_v5_foundation"
branch_labels = None
depends_on = None

TABLES = ("triage_assessments", "team_events", "actions", "action_events")


def upgrade() -> None:
    op.create_table('triage_assessments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('signal_kind', sa.String(length=30), nullable=False),
    sa.Column('observed_defect', sa.String(length=20), nullable=False),
    sa.Column('risk_flags', sa.JSON(), nullable=False),
    sa.Column('scope_lots', sa.JSON(), nullable=False),
    sa.Column('route', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('assessor_id', sa.String(length=40), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['assessor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_triage_assessments_case_id', 'triage_assessments', ['case_id'])
    op.create_table('team_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('responsibility', sa.String(length=20), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=True),
    sa.Column('event', sa.String(length=12), nullable=False),
    sa.Column('due_at', sa.String(length=40), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_team_events_case_id', 'team_events', ['case_id'])
    op.create_table('actions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('stage', sa.String(length=10), nullable=False),
    sa.Column('action_type', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('targets', sa.JSON(), nullable=False),
    sa.Column('target_snapshot', sa.JSON(), nullable=False),
    sa.Column('cause_ids', sa.JSON(), nullable=False),
    sa.Column('document_version_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_actions_case_id', 'actions', ['case_id'])
    op.create_table('action_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('action_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=24), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('occurred_at', sa.String(length=40), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('synthetic', sa.Boolean(), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_action_events_action_id', 'action_events', ['action_id'])
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
