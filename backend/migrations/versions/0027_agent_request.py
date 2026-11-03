"""Agent run request class: supported / needs info / unsupported / human only / partial (prompt §2, spec §22)"""

import sqlalchemy as sa
from alembic import op

revision = "0027_agent_request"
down_revision = "0026_calculations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agent_runs') as b:
        b.add_column(sa.Column('request', sa.JSON(), server_default='{}', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('agent_runs') as b:
        b.drop_column('request')
