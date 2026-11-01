"""RW: case origin profiles, requests with reply versions and reviews, and the responsibility event log"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0022_requests"
down_revision = "0021_vision_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('case_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(length=30), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('recorded_by', sa.String(length=40), nullable=False),
    sa.Column('recorded_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'version')
    )
    op.create_index('ix_case_profiles_case_id', 'case_profiles', ['case_id'])
    op.create_table('case_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('items_sha256', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.String(length=40), nullable=False),
    sa.Column('pending_owner_id', sa.String(length=40), nullable=True),
    sa.Column('reviewer_id', sa.String(length=40), nullable=False),
    sa.Column('external_party', sa.JSON(), nullable=True),
    sa.Column('due_at', sa.String(length=40), nullable=False),
    sa.Column('due_tz', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('submission_version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('updated_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['pending_owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_case_requests_case_id', 'case_requests', ['case_id'])
    op.create_table('request_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('files_sha256', sa.String(length=64), nullable=False),
    sa.Column('submitted_by', sa.JSON(), nullable=False),
    sa.Column('registered_by', sa.String(length=40), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.ForeignKeyConstraint(['registered_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['case_requests.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id', 'version')
    )
    op.create_index('ix_request_submissions_request_id', 'request_submissions', ['request_id'])
    op.create_table('request_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('submission_version', sa.Integer(), nullable=False),
    sa.Column('files_sha256', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('mode', sa.String(length=12), nullable=True),
    sa.Column('model', sa.String(length=60), nullable=True),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['case_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_request_reviews_request_id', 'request_reviews', ['request_id'])
    op.create_table('responsibility_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('subject', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.String(length=80), nullable=False),
    sa.Column('event', sa.String(length=30), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('actor_role', sa.String(length=30), nullable=False),
    sa.Column('from_user', sa.String(length=40), nullable=True),
    sa.Column('to_user', sa.String(length=40), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('target_version', sa.Integer(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_responsibility_events_case_id', 'responsibility_events', ['case_id'])
    for table in ("case_profiles", "request_submissions", "request_reviews", "responsibility_events"):
        for ddl in append_only_ddl(table):
            op.execute(ddl)


def downgrade() -> None:
    for table in ("responsibility_events", "request_reviews", "request_submissions", "case_requests",
                  "case_profiles"):
        op.drop_index(f"ix_{table}_{'case_id' if table in ('responsibility_events', 'case_requests', 'case_profiles') else 'request_id'}",
                      table_name=table)
        op.drop_table(table)
