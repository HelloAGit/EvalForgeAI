import os

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app.migrations import alembic_config
from app.models import entities  # noqa: F401


def _upgrade(url, target="head"):
    eng = create_engine(url)
    cfg = alembic_config()
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, target)
    return eng


def _schema(eng):
    insp = inspect(eng)
    return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names() if t != "alembic_version"}


def test_migrations_match_orm_metadata(tmp_path):
    eng = _upgrade(f"sqlite:///{tmp_path}/m.db")
    meta_eng = create_engine(f"sqlite:///{tmp_path}/meta.db")
    Base.metadata.create_all(meta_eng)
    assert _schema(eng) == _schema(meta_eng)


def test_upgrade_preserves_existing_history(tmp_path):
    url = f"sqlite:///{tmp_path}/legacy.db"
    eng = _upgrade(url, "0001")
    with eng.begin() as c:
        c.execute(text("INSERT INTO projects (id, name, created_at) VALUES ('p1', 'Legacy', '2025-01-01 00:00:00')"))
        c.execute(text("INSERT INTO evaluation_runs (id, project_id, model_name, status, created_at) VALUES ('r1','p1','legacy-model','COMPLETED','2025-01-01 00:00:00')"))
    eng2 = _upgrade(url)
    with eng2.begin() as c:
        assert c.execute(text("SELECT id FROM evaluation_runs")).scalar() == "r1"
    assert "report_snapshots" in inspect(eng2).get_table_names()
