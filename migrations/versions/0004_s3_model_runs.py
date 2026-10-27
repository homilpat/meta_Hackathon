"""S3 model runs and tool-call log."""

import sqlalchemy as sa
from alembic import op

revision = "0004_s3"
down_revision = "0003_s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
        op.create_table('model_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=False),
        sa.Column('requested_by', sa.String(length=40), nullable=False),
        sa.Column('model', sa.String(length=60), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('rounds', sa.Integer(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('report_json', sa.Text(), nullable=True),
        sa.Column('validation_errors', sa.JSON(), nullable=False),
        sa.Column('started_at', sa.String(length=40), nullable=False),
        sa.Column('finished_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('tool_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_run_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('tool_name', sa.String(length=60), nullable=False),
        sa.Column('arguments_json', sa.Text(), nullable=False),
        sa.Column('result_sha256', sa.String(length=64), nullable=True),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['model_run_id'], ['model_runs.id'], ),
        sa.PrimaryKeyConstraint('id')
        )


def downgrade() -> None:
        op.drop_table('tool_calls')
        op.drop_table('model_runs')
