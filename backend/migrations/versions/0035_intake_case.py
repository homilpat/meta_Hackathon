"""An intake remembers the case conversation it was uploaded in (one case per Agent conversation)."""

import sqlalchemy as sa
from alembic import op

revision = "0035_intake_case"
down_revision = "0034_request_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("intake_records") as b:
        b.add_column(sa.Column("case_id", sa.String(length=80), nullable=True))
        b.create_index(b.f("ix_intake_records_case_id"), ["case_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("intake_records") as b:
        b.drop_index(b.f("ix_intake_records_case_id"))
        b.drop_column("case_id")
