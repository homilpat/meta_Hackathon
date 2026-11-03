"""Every refused (4xx) or failed (5xx) request, recorded by one exception handler, for the agent's "왜 안 돼?"
(append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0034_request_errors"
down_revision = "0033_limit_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('request_errors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=True),
    sa.Column('case_id', sa.String(length=80), nullable=True),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('route', sa.String(length=200), nullable=False),
    sa.Column('target', sa.JSON(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_errors_user_id'), 'request_errors', ['user_id'], unique=False)
    for ddl in append_only_ddl("request_errors"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_index(op.f('ix_request_errors_user_id'), table_name='request_errors')
    op.drop_table('request_errors')
