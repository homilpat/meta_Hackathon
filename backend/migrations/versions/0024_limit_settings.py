"""Operating limits changed by the AI operations department (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0024_limit_settings"
down_revision = "0023_egress_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('limit_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    for ddl in append_only_ddl("limit_settings"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_table('limit_settings')
