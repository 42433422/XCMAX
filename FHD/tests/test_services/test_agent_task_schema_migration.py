from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "2026_08_10_erp_absorb_orthogonal"


def _config() -> Config:
    return Config(str(_PROJECT_ROOT / "alembic.ini"))


@pytest.fixture()
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'agent-task-schema.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def test_agent_task_migration_creates_ssot_and_command_ledger(database_url: str) -> None:
    command.upgrade(_config(), "head")

    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        assert {"agent_tasks", "agent_task_commands"} <= set(schema.get_table_names())
        assert {column["name"] for column in schema.get_columns("agent_tasks")} >= {
            "task_id",
            "tenant_id",
            "active_run_id",
            "attention_state",
            "archived_at",
        }
        assert {column["name"] for column in schema.get_columns("agent_task_commands")} >= {
            "command_id",
            "run_id",
            "action",
            "status",
            "applied_at",
        }
        assert {item["name"] for item in schema.get_unique_constraints("agent_tasks")} == {
            "uq_agent_tasks_tenant_user_task"
        }
    finally:
        engine.dispose()

    command.downgrade(_config(), _PREVIOUS_REVISION)
    engine = create_engine(database_url)
    try:
        assert not {"agent_tasks", "agent_task_commands"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_accepts_runtime_auto_created_task_tables(database_url: str) -> None:
    command.upgrade(_config(), _PREVIOUS_REVISION)

    from app.db.base import Base
    from app.db.models.agent import AgentTaskCommandRecord, AgentTaskRecord

    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(
            bind=engine,
            tables=[AgentTaskRecord.__table__, AgentTaskCommandRecord.__table__],
            checkfirst=True,
        )
    finally:
        engine.dispose()

    command.upgrade(_config(), "head")
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        assert {"agent_tasks", "agent_task_commands"} <= set(schema.get_table_names())
        assert "ix_agent_tasks_user_attention" in {
            item["name"] for item in schema.get_indexes("agent_tasks")
        }
        assert "ix_agent_task_commands_run_created" in {
            item["name"] for item in schema.get_indexes("agent_task_commands")
        }
    finally:
        engine.dispose()
