"""Stored model answers by exact request, so the same request gets the same answer (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0025_model_responses"
down_revision = "0024_limit_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('model_responses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_sha256', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('provider_mode', sa.String(length=20), nullable=False),
    sa.Column('message', sa.JSON(), nullable=False),
    sa.Column('usage', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_sha256')
    )
    for ddl in append_only_ddl("model_responses"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_table('model_responses')
