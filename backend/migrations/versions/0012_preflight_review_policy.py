"""v5.5 PREFLIGHT: record the WorkflowPolicy a review was requested under (nullable: older reviews have none)"""

import sqlalchemy as sa
from alembic import op

revision = "0012_preflight_review_policy"
down_revision = "0011_v5_d0_d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("policy_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch:
        batch.drop_column("policy_hash")
