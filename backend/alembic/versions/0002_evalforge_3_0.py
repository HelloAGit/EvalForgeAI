"""EvalForge 3.0: events, observations, scheduling, reports, videos

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("version", sa.String))
    for name, typ in [
        ("provider", sa.String), ("model_id", sa.String), ("suite", sa.String),
        ("dataset_id", sa.String), ("dataset_version", sa.String), ("category", sa.String),
        ("trigger", sa.String), ("schedule_job_id", sa.String), ("idempotency_key", sa.String),
        ("started_at", sa.DateTime), ("completed_at", sa.DateTime),
        ("error_message", sa.Text), ("config", sa.JSON),
    ]:
        op.add_column("evaluation_runs", sa.Column(name, typ))
    op.create_index("uq_runs_idempotency_key", "evaluation_runs", ["idempotency_key"], unique=True)
    op.create_index("ix_runs_filters", "evaluation_runs",
                    ["project_id", "provider", "model_id", "suite", "category"])
    op.create_index("ix_runs_created", "evaluation_runs", ["created_at"])
    for name, typ in [("status", sa.String), ("error_type", sa.String),
                      ("cost_usd", sa.Float), ("evidence", sa.JSON)]:
        op.add_column("evaluation_results", sa.Column(name, typ))
    op.create_index("ix_results_run", "evaluation_results", ["evaluation_run_id"])

    op.create_table(
        "evaluation_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("project_id", sa.String), sa.Column("run_id", sa.String),
        sa.Column("payload", sa.JSON), sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "metric_observations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("result_id", sa.String, sa.ForeignKey("evaluation_results.id")),
        sa.Column("sample_id", sa.String),
        sa.Column("metric_key", sa.String, nullable=False),
        sa.Column("catalog_key", sa.String),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("method", sa.String), sa.Column("method_version", sa.String),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_obs_catalog", "metric_observations", ["catalog_key", "run_id"])
    op.create_index("ix_obs_run", "metric_observations", ["run_id"])
    op.create_index("ix_obs_created", "metric_observations", ["created_at"])
    op.create_table(
        "metric_aggregates",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("catalog_key", sa.String, nullable=False),
        sa.Column("n", sa.Integer, nullable=False), sa.Column("mean", sa.Float, nullable=False),
        sa.Column("std", sa.Float), sa.Column("ci_low", sa.Float), sa.Column("ci_high", sa.Float),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("run_id", "catalog_key", name="uq_aggregate_run_metric"),
    )
    op.create_table(
        "statistical_results",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("snapshot_id", sa.String), sa.Column("project_id", sa.String),
        sa.Column("metric_key", sa.String, nullable=False),
        sa.Column("baseline_ref", sa.String, nullable=False),
        sa.Column("candidate_ref", sa.String, nullable=False),
        sa.Column("method", sa.String, nullable=False),
        sa.Column("sample_size_baseline", sa.Integer, nullable=False),
        sa.Column("sample_size_candidate", sa.Integer, nullable=False),
        sa.Column("mean_difference", sa.Float), sa.Column("p_value", sa.Float),
        sa.Column("effect_size", sa.Float), sa.Column("ci_low", sa.Float),
        sa.Column("ci_high", sa.Float), sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "dashboard_preferences",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("user_id", sa.String, nullable=False, unique=True),
        sa.Column("preferences", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("next_run_at", sa.DateTime), sa.Column("last_run_at", sa.DateTime),
        sa.Column("last_status", sa.String), sa.Column("last_skip_reason", sa.String),
        sa.Column("last_dataset_seen_at", sa.DateTime),
        sa.Column("max_runs_per_day", sa.Integer, nullable=False),
        sa.Column("created_by", sa.String), sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("project_id", sa.String),
        sa.Column("schema_version", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("payload_sha256", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "report_definitions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("template", sa.String, nullable=False),
        sa.Column("project_id", sa.String),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("snapshot_id", sa.String, sa.ForeignKey("report_snapshots.id")),
        sa.Column("current_artifact_id", sa.String),
        sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime),
    )
    op.create_table(
        "generated_artifacts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("report_id", sa.String), sa.Column("snapshot_id", sa.String),
        sa.Column("video_id", sa.String),
        sa.Column("storage_key", sa.String, nullable=False),
        sa.Column("content_type", sa.String, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String, nullable=False),
        sa.Column("meta", sa.JSON), sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("report_id", sa.String, sa.ForeignKey("report_definitions.id"), nullable=False),
        sa.Column("snapshot_id", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("stage", sa.String),
        sa.Column("progress", sa.Float, nullable=False),
        sa.Column("options", sa.JSON, nullable=False),
        sa.Column("storyboard", sa.JSON),
        sa.Column("storyboard_source", sa.String),
        sa.Column("validation", sa.JSON),
        sa.Column("approved_at", sa.DateTime), sa.Column("approved_hash", sa.String),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("locked_by", sa.String), sa.Column("lease_expires_at", sa.DateTime),
        sa.Column("error_message", sa.Text), sa.Column("artifact_id", sa.String),
        sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("ix_video_state", "video_jobs", ["state"])


def downgrade() -> None:
    op.drop_index("ix_video_state", table_name="video_jobs")
    for t in ("video_jobs", "generated_artifacts", "report_definitions", "report_snapshots",
              "scheduled_jobs", "dashboard_preferences", "statistical_results",
              "metric_aggregates", "metric_observations", "evaluation_events"):
        op.drop_table(t)
    op.drop_index("ix_results_run", table_name="evaluation_results")
    with op.batch_alter_table("evaluation_results") as b:
        for c in ("status", "error_type", "cost_usd", "evidence"):
            b.drop_column(c)
    for ix in ("ix_runs_created", "ix_runs_filters", "uq_runs_idempotency_key"):
        op.drop_index(ix, table_name="evaluation_runs")
    with op.batch_alter_table("evaluation_runs") as b:
        for c in ("provider", "model_id", "suite", "dataset_id", "dataset_version", "category",
                  "trigger", "schedule_job_id", "idempotency_key", "started_at", "completed_at",
                  "error_message", "config"):
            b.drop_column(c)
    with op.batch_alter_table("datasets") as b:
        b.drop_column("version")
