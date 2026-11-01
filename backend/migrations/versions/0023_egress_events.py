"""Egress: requests and decisions for external processing of an original file (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0023_egress_events"
down_revision = "0022_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('intake_egress_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('event', sa.String(length=12), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('actor_role', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['file_id'], ['intake_files.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_intake_egress_events_file_id', 'intake_egress_events', ['file_id'])
    for ddl in append_only_ddl("intake_egress_events"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_index('ix_intake_egress_events_file_id', table_name='intake_egress_events')
    op.drop_table('intake_egress_events')
