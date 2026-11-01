"""IN3: case origin / channel / owner (§25.1, §25.3) and intake-to-case links (append-only)"""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0020_intake_links"
down_revision = "0019_intake_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('quality_cases') as b:
        b.add_column(sa.Column('origin', sa.String(length=30), server_default='PROCESS_SIGNAL', nullable=False))
        b.add_column(sa.Column('channel', sa.String(length=20), server_default='MANUAL', nullable=False))
        b.add_column(sa.Column('owner_id', sa.String(length=40), nullable=True))
        b.create_foreign_key('fk_quality_cases_owner_id_users', 'users', ['owner_id'], ['id'])
    op.create_table('intake_case_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('intake_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('extraction_version', sa.Integer(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('linked_by', sa.String(length=40), nullable=False),
    sa.Column('linked_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['intake_id'], ['intake_records.id'], ),
    sa.ForeignKeyConstraint(['linked_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('intake_id')
    )
    op.create_index('ix_intake_case_links_case_id', 'intake_case_links', ['case_id'])
    for ddl in append_only_ddl("intake_case_links"):
        op.execute(ddl)


def downgrade() -> None:
    op.drop_index('ix_intake_case_links_case_id', table_name='intake_case_links')
    op.drop_table('intake_case_links')
    with op.batch_alter_table('quality_cases') as b:
        b.drop_constraint('fk_quality_cases_owner_id_users', type_='foreignkey')
        b.drop_column('owner_id')
        b.drop_column('channel')
        b.drop_column('origin')
