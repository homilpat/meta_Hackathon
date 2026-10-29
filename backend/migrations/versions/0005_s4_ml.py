"""S4 model versions, predictions, XAI artifacts; derived evidence has no source event."""

import sqlalchemy as sa
from alembic import op

revision = "0005_s4"
down_revision = "0004_s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('model_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('algorithm', sa.String(length=40), nullable=False),
    sa.Column('label_kind', sa.String(length=30), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('train_data_sha256', sa.String(length=64), nullable=False),
    sa.Column('feature_schema_sha256', sa.String(length=64), nullable=False),
    sa.Column('features', sa.JSON(), nullable=False),
    sa.Column('split', sa.JSON(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('threshold', sa.Double(), nullable=False),
    sa.Column('artifact_sha256', sa.String(length=64), nullable=False),
    sa.Column('artifact_text', sa.Text(), nullable=False),
    sa.Column('library_versions', sa.JSON(), nullable=False),
    sa.Column('trained_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('predictions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('model_version_id', sa.Integer(), nullable=False),
    sa.Column('target_key', sa.JSON(), nullable=False),
    sa.Column('risk_score', sa.Double(), nullable=False),
    sa.Column('threshold', sa.Double(), nullable=False),
    sa.Column('above_threshold', sa.Boolean(), nullable=False),
    sa.Column('features', sa.JSON(), nullable=False),
    sa.Column('input_evidence_ids', sa.JSON(), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('xai_artifacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prediction_id', sa.Integer(), nullable=False),
    sa.Column('method', sa.String(length=60), nullable=False),
    sa.Column('baseline', sa.Double(), nullable=False),
    sa.Column('contributions', sa.JSON(), nullable=False),
    sa.Column('raw_score', sa.Double(), nullable=False),
    sa.Column('additivity_error', sa.Double(), nullable=False),
    sa.Column('library_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.alter_column('source_event_id',
               existing_type=sa.INTEGER(),
               nullable=True)



def downgrade() -> None:
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.alter_column('source_event_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    op.drop_table('xai_artifacts')
    op.drop_table('predictions')
    op.drop_table('model_versions')
