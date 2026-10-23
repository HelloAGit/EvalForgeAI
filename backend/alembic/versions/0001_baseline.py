"""Baseline: EvalForge 2.0 schema

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("model_name", sa.String, nullable=False),
        sa.Column("status", sa.String),
        sa.Column("quality_index", sa.Float),
        sa.Column("metrics_summary", sa.JSON),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("evaluation_run_id", sa.String, sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("sample_id", sa.String, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("expected_output", sa.Text),
        sa.Column("actual_output", sa.Text),
        sa.Column("latency_ms", sa.Float),
        sa.Column("token_count", sa.Integer),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("mubit_request_id", sa.String),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    for t in ("evaluation_results", "evaluation_runs", "datasets", "projects"):
        op.drop_table(t)
