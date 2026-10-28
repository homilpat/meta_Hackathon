"""v5.5 G6: D5 action details, D6 effectiveness plans and results (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0014_v5_d5_d6"
down_revision = "0013_v5_d4"
branch_labels = None
depends_on = None

TABLES = ('effectiveness_plans', 'effectiveness_results')


def upgrade() -> None:
    op.create_table('effectiveness_plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('action_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=40), nullable=False),
    sa.Column('baseline_lots', sa.JSON(), nullable=False),
    sa.Column('post_from', sa.String(length=40), nullable=True),
    sa.Column('post_to', sa.String(length=40), nullable=True),
    sa.Column('min_sample', sa.Integer(), nullable=False),
    sa.Column('acceptance', sa.JSON(), nullable=False),
    sa.Column('inspection_conditions', sa.JSON(), nullable=False),
    sa.Column('monitoring', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_effectiveness_plans_action_id'), 'effectiveness_plans', ['action_id'], unique=False)
    op.create_index(op.f('ix_effectiveness_plans_case_id'), 'effectiveness_plans', ['case_id'], unique=False)
    op.create_table('effectiveness_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('action_id', sa.Integer(), nullable=False),
    sa.Column('computed', sa.String(length=20), nullable=False),
    sa.Column('observed', sa.JSON(), nullable=False),
    sa.Column('reasons', sa.JSON(), nullable=False),
    sa.Column('decision', sa.String(length=14), nullable=False),
    sa.Column('reviewer_id', sa.String(length=40), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['plan_id'], ['effectiveness_plans.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_effectiveness_results_case_id'), 'effectiveness_results', ['case_id'], unique=False)
    op.create_index(op.f('ix_effectiveness_results_plan_id'), 'effectiveness_results', ['plan_id'], unique=False)
    op.add_column('actions', sa.Column('details', sa.JSON(), nullable=True))
    for table in TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_table('effectiveness_results')
    op.drop_table('effectiveness_plans')
    with op.batch_alter_table('actions') as batch:
        batch.drop_column('details')
