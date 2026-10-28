from datetime import UTC, datetime

from sqlalchemy import DDL, JSON, ForeignKey, Integer, String, Text, UniqueConstraint, event
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
    raw_json: Mapped[str] = mapped_column(Text, deferred=True)  # whole asset; joins must not drag it per event


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
    # NULL for derived evidence (MODEL_PREDICTION / XAI_EXPLANATION) that has no source row
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("source_events.id"))
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



class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))  # AUTHOR REVIEWER QA_PRODUCTION PROCESS_ENGINEER


class Assignment(Base):
    """Case access scope: a user sees and acts on a case only through a row here."""

    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("case_id", "doc_type", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    doc_type: Mapped[str] = mapped_column(String(20))  # NCR | CONTAINMENT | RCA
    version: Mapped[int] = mapped_column(Integer)
    # DRAFT IN_REVIEW APPROVED REJECTED INFO_REQUESTED SUPERSEDED REVALIDATION_REQUIRED
    status: Mapped[str] = mapped_column(String(24))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    builder: Mapped[str] = mapped_column(String(60))
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
    based_on: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # ["NCR v1", ...]


class DocumentClaim(Base):
    __tablename__ = "document_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    claim_id: Mapped[str] = mapped_column(String(20))
    classification: Mapped[str] = mapped_column(String(20))  # OBSERVED CALCULATED HYPOTHESIS UNKNOWN
    text: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(20))
    evidence_ids: Mapped[list] = mapped_column(JSON)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(10))  # PENDING | DONE | HELD (source corrected)
    created_at: Mapped[str] = mapped_column(String(40))


class ApprovalEvent(Base):
    """Append-only decision bound to the exact content hash that was reviewed."""

    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))  # APPROVE REJECT REQUEST_INFO
    content_sha256: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(160), primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)


class ModelRun(Base):
    """One investigation attempt. mode is LIVE only for the real provider; failures are stored too."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    model: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20))  # LIVE | TEST_DOUBLE
    status: Mapped[str] = mapped_column(String(24))  # VALIDATED VALIDATION_FAILED FAILED JSON_ERROR LIMIT_EXCEEDED
    history_enabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    rounds: Mapped[int] = mapped_column(Integer)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    report_json: Mapped[str | None] = mapped_column(Text)
    validation_errors: Mapped[list] = mapped_column(JSON)
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str] = mapped_column(String(40))


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"))
    round: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(60))
    arguments_json: Mapped[str] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    ok: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    algorithm: Mapped[str] = mapped_column(String(40))
    label_kind: Mapped[str] = mapped_column(String(30))  # SYNTHETIC_LABEL until a real label is validated
    seed: Mapped[int] = mapped_column(Integer)
    train_data_sha256: Mapped[str] = mapped_column(String(64))
    feature_schema_sha256: Mapped[str] = mapped_column(String(64))
    features: Mapped[list] = mapped_column(JSON)
    split: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    threshold: Mapped[float]
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_text: Mapped[str] = mapped_column(Text)
    library_versions: Mapped[dict] = mapped_column(JSON)
    trained_at: Mapped[str] = mapped_column(String(40))


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    target_key: Mapped[list] = mapped_column(JSON)  # [panel_id, board_id]
    risk_score: Mapped[float]
    threshold: Mapped[float]
    above_threshold: Mapped[bool]
    features: Mapped[dict] = mapped_column(JSON)
    input_evidence_ids: Mapped[list] = mapped_column(JSON)
    input_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class XaiArtifact(Base):
    __tablename__ = "xai_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    method: Mapped[str] = mapped_column(String(60))
    baseline: Mapped[float]  # expected raw score (log-odds) over the training data
    contributions: Mapped[dict] = mapped_column(JSON)  # feature -> log-odds contribution
    raw_score: Mapped[float]
    additivity_error: Mapped[float]
    library_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))


class HistoricalCase(Base):
    """One snapshot of a closed past incident. SYNTHETIC bank in this project."""

    __tablename__ = "historical_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    historical_case_id: Mapped[str] = mapped_column(String(20), unique=True)
    snapshot_version: Mapped[int] = mapped_column(Integer)
    family: Mapped[str] = mapped_column(String(20))
    bank_version: Mapped[str] = mapped_column(String(30))
    site: Mapped[str] = mapped_column(String(40))
    source_origin: Mapped[str] = mapped_column(String(20))
    sensitivity: Mapped[str] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(20))  # APPROVED | DRAFT | RETRACTED
    superseded_by: Mapped[str | None] = mapped_column(String(20))
    process_stage: Mapped[str] = mapped_column(String(40))
    measurement_pattern: Mapped[str] = mapped_column(String(40))
    aoi_pattern: Mapped[str] = mapped_column(String(40))
    incident_at: Mapped[str] = mapped_column(String(40))
    available_at: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    limitations: Mapped[list] = mapped_column(JSON)
    source_version_hash: Mapped[str] = mapped_column(String(64))


class HistoricalEvidence(Base):
    __tablename__ = "historical_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    historical_case_id: Mapped[int] = mapped_column(ForeignKey("historical_cases.id"))
    ref_id: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)


class HistoricalOutcome(Base):
    """A check that was run and/or an action that was taken, with its observed status."""

    __tablename__ = "historical_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    historical_case_id: Mapped[int] = mapped_column(ForeignKey("historical_cases.id"))
    check: Mapped[str] = mapped_column(String(40))
    check_result: Mapped[str] = mapped_column(Text)
    check_status: Mapped[str] = mapped_column(String(20))
    action: Mapped[str | None] = mapped_column(String(40))
    action_status: Mapped[str] = mapped_column(String(20))  # NONE | PROPOSED | EXECUTED
    outcome_status: Mapped[str] = mapped_column(String(20))  # VERIFIED | INSUFFICIENT | FAILED | UNKNOWN
    metric: Mapped[str | None] = mapped_column(String(60))
    before: Mapped[float | None]
    after: Mapped[float | None]
    sample_count: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[str | None] = mapped_column(String(40))


class CaseLink(Base):
    """Human decision to use (or reject) a precedent for a current case. Never automatic."""

    __tablename__ = "case_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    historical_case_id: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(10))  # ACCEPTED | REJECTED
    note: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class EvidenceDependency(Base):
    """Edge src -> dst: EV/PRED -> PRED/XAI, evidence -> CLAIM:<doc>:<claim>, CLAIM -> DOC:<doc>."""

    __tablename__ = "evidence_dependencies"
    __table_args__ = (UniqueConstraint("case_id", "src", "dst"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    src: Mapped[str] = mapped_column(String(80), index=True)
    dst: Mapped[str] = mapped_column(String(80))


class ChangeImpact(Base):
    """Result of one source revision import: which nodes it reached and which documents it reopened."""

    __tablename__ = "change_impacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    asset_id: Mapped[str] = mapped_column(String(120))
    supersedes_asset_id: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    changed_evidence: Mapped[list] = mapped_column(JSON)
    impacted: Mapped[dict] = mapped_column(JSON)  # {"derived": [...], "claims": [...], "documents": [...]}
    created_at: Mapped[str] = mapped_column(String(40))


class DocComment(Base):
    """Review feedback anchored to a document version (optionally one claim). Resolving appends a row."""

    __tablename__ = "doc_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    claim_id: Mapped[str | None] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10))  # COMMENT | RESOLVE
    reply_to: Mapped[int | None] = mapped_column(ForeignKey("doc_comments.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class AuditChain(Base):
    """One link per audit row: sha256(prev link + row content). Lets app.audit.verify detect edits that bypass
    the triggers (e.g. an admin dropping them)."""

    __tablename__ = "audit_chain"
    __table_args__ = (UniqueConstraint("table_name", "row_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(30))
    row_id: Mapped[int] = mapped_column(Integer)
    prev_sha256: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))


class WorkflowPolicy(Base):
    """A versioned 8D policy: who may draft/execute/approve/close what. New behaviour = new version row."""

    __tablename__ = "workflow_policies"
    __table_args__ = (UniqueConstraint("policy_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    applicability: Mapped[dict] = mapped_column(JSON)  # site/customer/process_type/severity, "*" = any
    body: Mapped[dict] = mapped_column(JSON)
    policy_hash: Mapped[str] = mapped_column(String(64))
    effective_from: Mapped[str] = mapped_column(String(40))
    approved_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))


class EvidenceQuality(Base):
    """EvidenceQualityAssessment: one row per state change (rules or a named person); latest version wins."""

    __tablename__ = "evidence_quality"
    __table_args__ = (UniqueConstraint("case_id", "evidence_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"))
    evidence_id: Mapped[str] = mapped_column(String(30), index=True)
    version: Mapped[int] = mapped_column(Integer)
    quality_state: Mapped[str] = mapped_column(String(12))  # VALID SUSPECT CONFLICTED SUPERSEDED UNVERIFIED
    reason: Mapped[str] = mapped_column(Text)
    measurements: Mapped[dict] = mapped_column(JSON)  # the checks behind the state
    checked_by: Mapped[str] = mapped_column(String(40))  # SYSTEM_RULES or a user id
    created_at: Mapped[str] = mapped_column(String(40))


class ProcessContext(Base):
    __tablename__ = "process_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"), unique=True)
    site: Mapped[str] = mapped_column(String(40))
    customer: Mapped[str] = mapped_column(String(60))
    process_type: Mapped[str] = mapped_column(String(40))
    adapter_version: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(60))
    equipment: Mapped[list] = mapped_column(JSON)
    recipe: Mapped[str | None] = mapped_column(String(60))
    config_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class AffectedObject(Base):
    """Process-neutral view of lots/panels/parts in scope, with shipment state, snapshotted from adapter output."""

    __tablename__ = "affected_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[str | None] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(String(60))
    shipment_state: Mapped[str] = mapped_column(String(20))  # IN_PLANT SHIPPED UNKNOWN
    identity_source: Mapped[str] = mapped_column(String(30))  # evidence id the identity comes from


class TriageAssessment(Base):
    """D0: what was seen (signal kind) is stored apart from whether a defect is confirmed; latest row wins."""

    __tablename__ = "triage_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"), index=True)
    signal_kind: Mapped[str] = mapped_column(String(30))  # SPC_SIGNAL AOI_FAIL CUSTOMER_COMPLAINT OTHER
    observed_defect: Mapped[str] = mapped_column(String(20))  # SIGNAL_ONLY DEFECT_CONFIRMED UNKNOWN
    risk_flags: Mapped[dict] = mapped_column(JSON)
    scope_lots: Mapped[list] = mapped_column(JSON)
    route: Mapped[str] = mapped_column(String(20))  # NCR_ONLY FULL_8D EMERGENCY_FULL_8D
    severity: Mapped[str] = mapped_column(String(10))
    rationale: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON)
    assessor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    policy_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class TeamEvent(Base):
    """D1 membership as events (ASSIGNED / ACCEPTED / DECLINED / EXCEPTION); current team is derived."""

    __tablename__ = "team_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"), index=True)
    responsibility: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(12))
    due_at: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class Action(Base):
    """Urgent (pre-D1) and D3/D5/D6 actions. The record is the plan; what happened is in action_events."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("quality_cases.id"), index=True)
    stage: Mapped[str] = mapped_column(String(10))  # URGENT D3 D5
    action_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    targets: Mapped[list] = mapped_column(JSON)  # affected object ids, bound at creation
    target_snapshot: Mapped[list] = mapped_column(JSON)  # their shipment state + identity evidence at creation
    cause_ids: Mapped[list] = mapped_column(JSON, default=list)  # D5: confirmed cause hypothesis ids
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class ActionEvent(Base):
    """ActionExecution and friends. In this repository every EXECUTED event is SIMULATED (synthetic data)."""

    __tablename__ = "action_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[list] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text)
    synthetic: Mapped[bool] = mapped_column(default=True)
    policy_hash: Mapped[str] = mapped_column(String(64))


# Audit rows are append-only at the database level, not just by convention.
APPEND_ONLY = ("approval_events", "workflow_events", "doc_comments", "audit_chain",
               "workflow_policies", "evidence_quality", "process_contexts", "affected_objects",
               "triage_assessments", "team_events", "actions", "action_events")


def append_only_ddl(table: str) -> list[str]:
    return [f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END" for op in ("UPDATE", "DELETE")]


for _table in APPEND_ONLY:
    for _ddl in append_only_ddl(_table):
        event.listen(Base.metadata.tables[_table], "after_create", DDL(_ddl).execute_if(dialect="sqlite"))
