"""Programmatic Alembic upgrade used on application start-up."""
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import engine

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config() -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "alembic"))
    return cfg


def upgrade_database() -> None:
    """Upgrade to head. Databases created by EvalForge 2.0 (``create_all`` with
    no alembic_version table) are stamped at the baseline first so existing
    evaluation history is preserved."""
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and "evaluation_runs" in tables:
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")
