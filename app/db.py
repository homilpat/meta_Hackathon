from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QualityCase(Base):
    __tablename__ = "quality_cases"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    domain: Mapped[str] = mapped_column(String(40))
    data_origin: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now(UTC).isoformat())


class SourceAsset(Base):
    __tablename__ = "source_assets"
    __table_args__ = (UniqueConstraint("case_id", "asset_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    asset_id: Mapped[str] = mapped_column(String(120))
    source_system: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    source_version: Mapped[int] = mapped_column(Integer)
    supersedes_asset_id: Mapped[str | None] = mapped_column(String(120))
    license_id: Mapped[str] = mapped_column(String(80))
    data_origin: Mapped[str] = mapped_column(String(20))
    sensitivity: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[str] = mapped_column(String(40))
    ingested_at: Mapped[str] = mapped_column(String(40))
    content_sha256: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[str] = mapped_column(Text)


class SourceEvent(Base):
    __tablename__ = "source_events"
    __table_args__ = (UniqueConstraint("case_id", "event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    source_asset_id: Mapped[int] = mapped_column(ForeignKey("source_assets.id"))
    event_id: Mapped[str] = mapped_column(String(20))
    original_row_id: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_key: Mapped[list] = mapped_column(JSON)
    event_time: Mapped[str] = mapped_column(String(40))
    source_updated_at: Mapped[str | None] = mapped_column(String(40))
    ingested_at: Mapped[str] = mapped_column(String(40))
    data_origin: Mapped[str] = mapped_column(String(20))
    sensitivity: Mapped[str] = mapped_column(String(40))
    validation_status: Mapped[str] = mapped_column(String(30))
    raw_json: Mapped[str] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("case_id", "evidence_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    source_event_id: Mapped[int] = mapped_column(ForeignKey("source_events.id"))
    evidence_id: Mapped[str] = mapped_column(String(30))
    classification: Mapped[str] = mapped_column(String(30))
    validity: Mapped[str] = mapped_column(String(30))
    content_sha256: Mapped[str] = mapped_column(String(64))


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    event_id: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text)

