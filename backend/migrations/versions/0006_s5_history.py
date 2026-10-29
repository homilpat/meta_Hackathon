"""S5 historical case bank, outcomes, evidence refs, case links; model_runs.history_enabled."""

import sqlalchemy as sa
from alembic import op

revision = "0006_s5"
down_revision = "0005_s4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('historical_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('historical_case_id', sa.String(length=20), nullable=False),
    sa.Column('snapshot_version', sa.Integer(), nullable=False),
    sa.Column('family', sa.String(length=20), nullable=False),
    sa.Column('bank_version', sa.String(length=30), nullable=False),
    sa.Column('site', sa.String(length=40), nullable=False),
    sa.Column('source_origin', sa.String(length=20), nullable=False),
    sa.Column('sensitivity', sa.String(length=40), nullable=False),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('superseded_by', sa.String(length=20), nullable=True),
    sa.Column('process_stage', sa.String(length=40), nullable=False),
    sa.Column('measurement_pattern', sa.String(length=40), nullable=False),
    sa.Column('aoi_pattern', sa.String(length=40), nullable=False),
    sa.Column('incident_at', sa.String(length=40), nullable=False),
    sa.Column('available_at', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('limitations', sa.JSON(), nullable=False),
    sa.Column('source_version_hash', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('historical_case_id')
    )
    op.create_table('case_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('historical_case_id', sa.String(length=20), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('historical_evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('historical_case_id', sa.Integer(), nullable=False),
    sa.Column('ref_id', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['historical_case_id'], ['historical_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('historical_outcomes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('historical_case_id', sa.Integer(), nullable=False),
    sa.Column('check', sa.String(length=40), nullable=False),
    sa.Column('check_result', sa.Text(), nullable=False),
    sa.Column('check_status', sa.String(length=20), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=True),
    sa.Column('action_status', sa.String(length=20), nullable=False),
    sa.Column('outcome_status', sa.String(length=20), nullable=False),
    sa.Column('metric', sa.String(length=60), nullable=True),
    sa.Column('before', sa.Double(), nullable=True),
    sa.Column('after', sa.Double(), nullable=True),
    sa.Column('sample_count', sa.Integer(), nullable=True),
    sa.Column('verified_at', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['historical_case_id'], ['historical_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('model_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('history_enabled', sa.Boolean(), server_default='0', nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('model_runs', schema=None) as batch_op:
        batch_op.drop_column('history_enabled')

    op.drop_table('historical_outcomes')
    op.drop_table('historical_evidence')
    op.drop_table('case_links')
    op.drop_table('historical_cases')
