"""S1 provenance, events, evidence, and data quality issues."""

import sqlalchemy as sa
from alembic import op

revision = "0002_s1"
down_revision = "0001_s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_cases",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("data_origin", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "source_assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.String(80), sa.ForeignKey("quality_cases.id"), nullable=False),
        sa.Column("asset_id", sa.String(120), nullable=False),
        sa.Column("source_system", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("source_version", sa.Integer, nullable=False),
        sa.Column("supersedes_asset_id", sa.String(120)),
        sa.Column("license_id", sa.String(80), nullable=False),
        sa.Column("data_origin", sa.String(20), nullable=False),
        sa.Column("sensitivity", sa.String(40), nullable=False),
        sa.Column("captured_at", sa.String(40), nullable=False),
        sa.Column("ingested_at", sa.String(40), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("raw_json", sa.Text, nullable=False),
        sa.UniqueConstraint("case_id", "asset_id"),
    )
    op.create_table(
        "source_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.String(80), sa.ForeignKey("quality_cases.id"), nullable=False),
        sa.Column("source_asset_id", sa.Integer, sa.ForeignKey("source_assets.id"), nullable=False),
        sa.Column("event_id", sa.String(20), nullable=False),
        sa.Column("original_row_id", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_key", sa.JSON, nullable=False),
        sa.Column("event_time", sa.String(40), nullable=False),
        sa.Column("source_updated_at", sa.String(40)),
        sa.Column("ingested_at", sa.String(40), nullable=False),
        sa.Column("data_origin", sa.String(20), nullable=False),
        sa.Column("sensitivity", sa.String(40), nullable=False),
        sa.Column("validation_status", sa.String(30), nullable=False),
        sa.Column("raw_json", sa.Text, nullable=False),
        sa.UniqueConstraint("case_id", "event_id"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.String(80), sa.ForeignKey("quality_cases.id"), nullable=False),
        sa.Column("source_event_id", sa.Integer, sa.ForeignKey("source_events.id"), nullable=False),
        sa.Column("evidence_id", sa.String(30), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("validity", sa.String(30), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("case_id", "evidence_id"),
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.String(80), sa.ForeignKey("quality_cases.id"), nullable=False),
        sa.Column("event_id", sa.String(20), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("data_quality_issues")
    op.drop_table("evidence")
    op.drop_table("source_events")
    op.drop_table("source_assets")
    op.drop_table("quality_cases")
