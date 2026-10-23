import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, Text, JSON, Integer, Boolean,
    Index, UniqueConstraint, event,
)
from sqlalchemy.orm import relationship
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC timestamp (all timestamps in the database are UTC)."""
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    evaluations = relationship("EvaluationRun", back_populates="project")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # llm, rag, agent
    content = Column(JSON, nullable=False)
    version = Column(String, nullable=True, default="v1")
    created_at = Column(DateTime, default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    model_name = Column(String, nullable=False)
    status = Column(String, default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    quality_index = Column(Float, nullable=True)
    metrics_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # --- 3.0 additions (all nullable for backwards compatibility) ---
    provider = Column(String, nullable=True)
    model_id = Column(String, nullable=True)
    suite = Column(String, nullable=True)
    dataset_id = Column(String, nullable=True)
    dataset_version = Column(String, nullable=True)
    category = Column(String, nullable=True)  # llm | rag | agent
    trigger = Column(String, nullable=True)  # manual | scheduled | dataset | release
    schedule_job_id = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, unique=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)

    project = relationship("Project", back_populates="evaluations")
    results = relationship("EvaluationResult", back_populates="evaluation_run")

    __table_args__ = (
        Index("ix_runs_filters", "project_id", "provider", "model_id", "suite", "category"),
        Index("ix_runs_created", "created_at"),
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    evaluation_run_id = Column(String, ForeignKey("evaluation_runs.id"), nullable=False)
    sample_id = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    expected_output = Column(Text, nullable=True)
    actual_output = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=True)
    token_count = Column(Integer, nullable=True)
    metrics = Column(JSON, nullable=False)
    mubit_request_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # --- 3.0 additions ---
    status = Column(String, nullable=True)  # PASSED | FAILED | ERROR | COMPLETED
    error_type = Column(String, nullable=True)
    cost_usd = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=True)

    evaluation_run = relationship("EvaluationRun", back_populates="results")

    __table_args__ = (Index("ix_results_run", "evaluation_run_id"),)


class EvaluationEvent(Base):
    """Append-only change log; the autoincrement id is the SSE event id."""
    __tablename__ = "evaluation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False)  # run.created | results.added | run.completed | run.failed | ...
    project_id = Column(String, nullable=True)
    run_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class MetricObservation(Base):
    __tablename__ = "metric_observations"

    id = Column(String, primary_key=True, default=generate_uuid)
    run_id = Column(String, ForeignKey("evaluation_runs.id"), nullable=False)
    result_id = Column(String, ForeignKey("evaluation_results.id"), nullable=True)
    sample_id = Column(String, nullable=True)
    metric_key = Column(String, nullable=False)  # name as reported by the evaluator
    catalog_key = Column(String, nullable=True)  # resolved metrics-catalogue key
    value = Column(Float, nullable=False)
    method = Column(String, nullable=True)
    method_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_obs_catalog", "catalog_key", "run_id"),
        Index("ix_obs_run", "run_id"),
        Index("ix_obs_created", "created_at"),
    )


class MetricAggregate(Base):
    """Per run + metric aggregate, refreshed whenever observations are added."""
    __tablename__ = "metric_aggregates"

    id = Column(String, primary_key=True, default=generate_uuid)
    run_id = Column(String, ForeignKey("evaluation_runs.id"), nullable=False)
    catalog_key = Column(String, nullable=False)
    n = Column(Integer, nullable=False)
    mean = Column(Float, nullable=False)
    std = Column(Float, nullable=True)
    ci_low = Column(Float, nullable=True)
    ci_high = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("run_id", "catalog_key", name="uq_aggregate_run_metric"),)


class StatisticalResult(Base):
    __tablename__ = "statistical_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    snapshot_id = Column(String, nullable=True)
    project_id = Column(String, nullable=True)
    metric_key = Column(String, nullable=False)
    baseline_ref = Column(String, nullable=False)
    candidate_ref = Column(String, nullable=False)
    method = Column(String, nullable=False)
    sample_size_baseline = Column(Integer, nullable=False)
    sample_size_candidate = Column(Integer, nullable=False)
    mean_difference = Column(Float, nullable=True)
    p_value = Column(Float, nullable=True)
    effect_size = Column(Float, nullable=True)
    ci_low = Column(Float, nullable=True)
    ci_high = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class DashboardPreference(Base):
    __tablename__ = "dashboard_preferences"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=False, unique=True)
    preferences = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # daily | weekly | dataset_trigger | regression
    enabled = Column(Boolean, default=False, nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    config = Column(JSON, nullable=False)  # model_id, provider, suite, dataset_id, dataset_type, ...
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)
    last_skip_reason = Column(String, nullable=True)
    last_dataset_seen_at = Column(DateTime, nullable=True)
    max_runs_per_day = Column(Integer, default=4, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ReportDefinition(Base):
    """A report request. Its id is the public ``report_id``."""
    __tablename__ = "report_definitions"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    template = Column(String, nullable=False)  # executive | technical | statistical
    project_id = Column(String, nullable=True)
    config = Column(JSON, nullable=False)
    status = Column(String, default="PENDING", nullable=False)  # PENDING | GENERATING | COMPLETED | FAILED
    error_message = Column(Text, nullable=True)
    snapshot_id = Column(String, ForeignKey("report_snapshots.id"), nullable=True)
    current_artifact_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ReportSnapshot(Base):
    """Immutable canonical payload shared by PDF and video generation."""
    __tablename__ = "report_snapshots"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(String, nullable=False)
    project_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    payload_sha256 = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


@event.listens_for(ReportSnapshot, "before_update")
def _snapshot_no_update(mapper, connection, target):
    raise ValueError("Report snapshots are immutable")


@event.listens_for(ReportSnapshot, "before_delete")
def _snapshot_no_delete(mapper, connection, target):
    raise ValueError("Report snapshots are immutable")


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # pdf | video
    report_id = Column(String, nullable=True)
    snapshot_id = Column(String, nullable=True)
    video_id = Column(String, nullable=True)
    storage_key = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(String, nullable=False)
    report_id = Column(String, ForeignKey("report_definitions.id"), nullable=False)
    snapshot_id = Column(String, nullable=False)
    # QUEUED | GENERATING_SCRIPT | AWAITING_APPROVAL | RENDERING | COMPLETED | FAILED | CANCELLED
    state = Column(String, default="QUEUED", nullable=False)
    stage = Column(String, nullable=True)
    progress = Column(Float, default=0.0, nullable=False)
    options = Column(JSON, nullable=False)
    storyboard = Column(JSON, nullable=True)
    storyboard_source = Column(String, nullable=True)  # claude | template
    validation = Column(JSON, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_hash = Column(String, nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    locked_by = Column(String, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    artifact_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_video_state", "state"),)
