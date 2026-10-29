"""Security: tamper-evident hash chain over the append-only audit tables (backfills existing rows)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app import audit
from app.db import append_only_ddl

revision = "0009_audit_chain"
down_revision = "0008_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_chain',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('table_name', sa.String(length=30), nullable=False),
    sa.Column('row_id', sa.Integer(), nullable=False),
    sa.Column('prev_sha256', sa.String(length=64), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('table_name', 'row_id')
    )
    for ddl in append_only_ddl("audit_chain"):
        op.execute(ddl)
    audit.backfill(Session(bind=op.get_bind()))


def downgrade() -> None:
    op.drop_table('audit_chain')
