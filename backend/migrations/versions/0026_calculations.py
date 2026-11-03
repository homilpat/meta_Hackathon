"""Server calculations cited by id (append-only) and the attempts of an investigation run (spec §27.2-27.3)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0026_calculations"
down_revision = "0025_model_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('calculations',
    sa.Column('id', sa.String(length=30), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('operation', sa.String(length=10), nullable=False),
    sa.Column('field', sa.String(length=60), nullable=True),
    sa.Column('value', sa.Double(), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('input_evidence_ids', sa.JSON(), nullable=False),
    sa.Column('denominator_evidence_ids', sa.JSON(), nullable=False),
    sa.Column('filters', sa.JSON(), nullable=False),
    sa.Column('missing_policy', sa.Text(), nullable=False),
    sa.Column('denominator_definition', sa.Text(), nullable=True),
    sa.Column('source_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calculations_case_id'), 'calculations', ['case_id'], unique=False)
    for ddl in append_only_ddl("calculations"):
        op.execute(ddl)
    with op.batch_alter_table('model_runs') as b:
        b.add_column(sa.Column('attempts', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('model_runs') as b:
        b.drop_column('attempts')
    op.drop_index(op.f('ix_calculations_case_id'), table_name='calculations')
    op.drop_table('calculations')
