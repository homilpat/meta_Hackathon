"""§30 (v5.15): customer DOCX forms with their proposals, confirmed mappings and exports (DOC-OUT-01..04), and
held calculations with the questions, answers and resumes of missing inputs (ASK-RESUME-01..03). All append-only."""

import sqlalchemy as sa
from alembic import op

from app.db import append_only_ddl

revision = "0031_customer_forms_inputs"
down_revision = "0030_inspection_mapping_proposals"
branch_labels = None
depends_on = None

TABLES = ("customer_templates", "customer_template_proposals", "customer_template_mappings",
          "customer_template_exports", "input_requests", "input_events")


def _by():
    return [sa.Column('created_by', sa.String(length=40), nullable=False),
            sa.Column('created_at', sa.String(length=40), nullable=False),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], )]


def upgrade() -> None:
    op.create_table('customer_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('customer', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('slots', sa.JSON(), nullable=False),
    sa.Column('structure_sha', sa.String(length=64), nullable=False),
    sa.Column('data_origin', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    *_by(),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customer_templates_customer'), 'customer_templates', ['customer'], unique=False)
    op.create_table('customer_template_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('sent', sa.JSON(), nullable=False),
    sa.Column('reply', sa.JSON(), nullable=True),
    sa.Column('proposal', sa.JSON(), nullable=True),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('usage', sa.JSON(), nullable=False),
    *_by(),
    sa.ForeignKeyConstraint(['template_id'], ['customer_templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customer_template_proposals_template_id'), 'customer_template_proposals',
                    ['template_id'], unique=False)
    op.create_table('customer_template_mappings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('mapping', sa.JSON(), nullable=False),
    sa.Column('required', sa.JSON(), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=True),
    sa.Column('edits', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    *_by(),
    sa.ForeignKeyConstraint(['template_id'], ['customer_templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customer_template_mappings_template_id'), 'customer_template_mappings',
                    ['template_id'], unique=False)
    op.create_table('customer_template_exports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('template_version', sa.Integer(), nullable=False),
    sa.Column('mapping_id', sa.Integer(), nullable=True),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('case_data_version', sa.String(length=20), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    *_by(),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['customer_templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customer_template_exports_case_id'), 'customer_template_exports', ['case_id'],
                    unique=False)
    op.create_table('input_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=80), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('lot', sa.String(length=60), nullable=False),
    sa.Column('period', sa.String(length=40), nullable=True),
    sa.Column('missing_field', sa.String(length=40), nullable=False),
    sa.Column('held', sa.JSON(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    *_by(),
    sa.ForeignKeyConstraint(['case_id'], ['quality_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_input_requests_case_id'), 'input_requests', ['case_id'], unique=False)
    op.create_table('input_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('actor_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['input_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_input_events_request_id'), 'input_events', ['request_id'], unique=False)
    for t in TABLES:
        for ddl in append_only_ddl(t):
            op.execute(ddl)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
