"""Collaboration: append-only review comments anchored to a document version / claim"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0008_comments"
down_revision = "0007_s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('doc_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('document_version_id', sa.Integer(), nullable=False),
    sa.Column('claim_id', sa.String(length=20), nullable=True),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('reply_to', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['reply_to'], ['doc_comments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    for ddl in append_only_ddl("doc_comments"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_table('doc_comments')
