"""§30 follow-up: the per-slot value format a person confirmed (customer_docx.FORMATS) on a customer form mapping"""

import sqlalchemy as sa
from alembic import op

revision = "0032_customer_mapping_formats"
down_revision = "0031_customer_forms_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # plain ADD COLUMN, not a batch copy: a copied table would lose its append-only triggers
    op.add_column('customer_template_mappings', sa.Column('formats', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('customer_template_mappings') as b:
        b.drop_column('formats')
