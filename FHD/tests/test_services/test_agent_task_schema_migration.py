from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
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
        assert {"agent_tasks", "agent_task_commands", "agent_task_executions"} <= set(
            schema.get_table_names()
        )
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
        assert {column["name"] for column in schema.get_columns("agent_task_executions")} >= {
            "run_id",
            "state",
            "lease_owner",
            "lease_expires_at",
            "execution_count",
            "recovery_count",
        }
        assert {item["name"] for item in schema.get_unique_constraints("agent_tasks")} == {
            "uq_agent_tasks_tenant_user_task"
        }
    finally:
        engine.dispose()

    command.downgrade(_config(), _PREVIOUS_REVISION)
    engine = create_engine(database_url)
    try:
        assert not {"agent_tasks", "agent_task_commands", "agent_task_executions"} & set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()


def test_migration_accepts_runtime_auto_created_task_tables(database_url: str) -> None:
    command.upgrade(_config(), _PREVIOUS_REVISION)

    from app.db.base import Base
    from app.db.models.agent import (
        AgentTaskCommandRecord,
        AgentTaskExecutionRecord,
        AgentTaskRecord,
    )

    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(
            bind=engine,
            tables=[
                AgentTaskRecord.__table__,
                AgentTaskCommandRecord.__table__,
                AgentTaskExecutionRecord.__table__,
            ],
            checkfirst=True,
        )
    finally:
        engine.dispose()

    command.upgrade(_config(), "head")
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        assert {"agent_tasks", "agent_task_commands", "agent_task_executions"} <= set(
            schema.get_table_names()
        )
        assert "ix_agent_tasks_user_attention" in {
            item["name"] for item in schema.get_indexes("agent_tasks")
        }
        assert "ix_agent_task_commands_run_created" in {
            item["name"] for item in schema.get_indexes("agent_task_commands")
        }
        assert "ix_agent_task_executions_queue" in {
            item["name"] for item in schema.get_indexes("agent_task_executions")
        }
    finally:
        engine.dispose()


def test_migration_repairs_legacy_cross_tenant_unique_constraint(database_url: str) -> None:
    command.upgrade(_config(), _PREVIOUS_REVISION)
    engine = create_engine(database_url)
    metadata = sa.MetaData()
    sa.Table(
        "agent_tasks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(160), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("source", sa.String(48), nullable=False, server_default="agent"),
        sa.Column("task_type", sa.String(48), nullable=False, server_default="agent"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attention_state", sa.String(32), nullable=False, server_default=""),
        sa.Column("active_run_id", sa.String(96)),
        sa.Column("root_run_id", sa.String(96)),
        sa.Column("conversation_id", sa.String(160)),
        sa.Column("workspace_id", sa.String(160)),
        sa.Column("workspace_path", sa.Text()),
        sa.Column("workspace_isolation", sa.String(48), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.String(48)),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("user_id", "task_id", name="uq_agent_tasks_user_task"),
    )
    metadata.create_all(engine)
    engine.dispose()

    command.upgrade(_config(), "head")
    engine = create_engine(database_url)
    try:
        constraints = {
            item["name"] for item in inspect(engine).get_unique_constraints("agent_tasks")
        }
        assert constraints == {"uq_agent_tasks_tenant_user_task"}
    finally:
        engine.dispose()
