"""S2 workflow: users, assignments, NCR versions/claims, reviews, approvals, audit, idempotency."""

import sqlalchemy as sa
from alembic import op

revision = "0003_s2"
down_revision = "0002_s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
        op.create_table('idempotency_keys',
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        sa.Column('endpoint', sa.String(length=160), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('response_json', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('key', 'user_id', 'endpoint')
        )
        op.create_table('users',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'user_id')
        )
        op.create_table('document_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=False),
        sa.Column('doc_type', sa.String(length=10), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('author_id', sa.String(length=40), nullable=False),
        sa.Column('builder', sa.String(length=60), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'doc_type', 'version')
        )
        op.create_table('approval_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_version_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.String(length=40), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('document_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_version_id', sa.Integer(), nullable=False),
        sa.Column('claim_id', sa.String(length=20), nullable=False),
        sa.Column('classification', sa.String(length=20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('value', sa.Double(), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('evidence_ids', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_version_id', sa.Integer(), nullable=False),
        sa.Column('requested_by', sa.String(length=40), nullable=False),
        sa.Column('reviewer_id', sa.String(length=40), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('workflow_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=False),
        sa.Column('document_version_id', sa.Integer(), nullable=True),
        sa.Column('actor_id', sa.String(length=40), nullable=False),
        sa.Column('event', sa.String(length=30), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
        sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
        sa.PrimaryKeyConstraint('id')
        )


def downgrade() -> None:
        op.drop_table('workflow_events')
        op.drop_table('reviews')
        op.drop_table('document_claims')
        op.drop_table('approval_events')
        op.drop_table('document_versions')
        op.drop_table('assignments')
        op.drop_table('users')
        op.drop_table('idempotency_keys')
