"""v5.14 AI-CFG-04: AI-proposed operating-limit changes and a person's decisions on them (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0033_limit_proposals"
down_revision = "0032_customer_mapping_formats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('limit_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('current_value', sa.Text(), nullable=False),
    sa.Column('proposed_value', sa.Text(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('statistics', sa.JSON(), nullable=False),
    sa.Column('snapshot_sha', sa.String(length=16), nullable=False),
    sa.Column('comparison', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('issue', sa.Text(), nullable=True),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('usage', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('limit_proposal_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['proposal_id'], ['limit_proposals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_limit_proposal_decisions_proposal_id'), 'limit_proposal_decisions', ['proposal_id'],
                    unique=False)
    for t in ("limit_proposals", "limit_proposal_decisions"):
        for ddl in append_only_ddl(t):
            op.execute(ddl)


def downgrade() -> None:
    op.drop_index(op.f('ix_limit_proposal_decisions_proposal_id'), table_name='limit_proposal_decisions')
    op.drop_table('limit_proposal_decisions')
    op.drop_table('limit_proposals')
