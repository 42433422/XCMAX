"""Runtime contract for an Alembic-owned database schema."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable
from weakref import WeakSet

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

_DDL_PATTERN = re.compile(
    r"^\s*(?:/\*.*?\*/\s*)*(CREATE|ALTER|DROP|TRUNCATE|REINDEX)\b",
    re.IGNORECASE | re.DOTALL,
)
_runtime_guard_active = False
_guarded_engines: WeakSet[Engine] = WeakSet()


class SchemaMigrationRequired(RuntimeError):
    """The database is not at the repository's exact Alembic head."""


class RuntimeSchemaMutationForbidden(RuntimeError):
    """Application code attempted DDL after Alembic handed off the database."""


def _alembic_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def expected_schema_heads() -> set[str]:
    root = _alembic_root()
    ini = root / "alembic.ini"
    if not ini.is_file() and (root / "alembic.ini" / "alembic.ini").is_file():
        ini = root / "alembic.ini" / "alembic.ini"
        root = ini.parent
    if not ini.is_file():
        raise SchemaMigrationRequired(f"alembic.ini not found: {ini}")
    config = Config(str(ini))
    config.set_main_option("script_location", str(root / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def current_schema_heads(engine: Engine) -> set[str]:
    if "alembic_version" not in set(inspect(engine).get_table_names()):
        return set()
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version"))
        return {str(row[0]).strip() for row in rows if str(row[0]).strip()}


def assert_database_schema_at_head(engine: Engine) -> None:
    """Fail closed unless the connected DB is on every current Alembic head."""
    expected = expected_schema_heads()
    current = current_schema_heads(engine)
    if current != expected:
        current_label = ", ".join(sorted(current)) or "<unversioned>"
        expected_label = ", ".join(sorted(expected)) or "<no repository head>"
        raise SchemaMigrationRequired(
            "database schema is not at Alembic head "
            f"(current={current_label}; expected={expected_label}). "
            "Run `alembic -c alembic.ini upgrade head` before starting the application."
        )


def assert_tables_present(engine: Engine, required_tables: Iterable[str]) -> None:
    """Fail closed when a migration-owned runtime table is missing."""
    required = {str(name).strip() for name in required_tables if str(name).strip()}
    missing = sorted(required - set(inspect(engine).get_table_names()))
    if missing:
        raise SchemaMigrationRequired(
            "migration-owned tables are missing: "
            + ", ".join(missing)
            + ". Run `alembic -c alembic.ini upgrade head`."
        )


def install_runtime_ddl_guard(engine: Engine) -> None:
    """Block application DDL on a migration-owned engine."""
    if engine in _guarded_engines:
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _reject_runtime_ddl(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if _DDL_PATTERN.match(str(statement or "")):
            raise RuntimeSchemaMutationForbidden(
                "runtime DDL is forbidden on the Alembic-owned database; "
                "add an Alembic migration instead"
            )

    _guarded_engines.add(engine)


def activate_runtime_ddl_guard() -> None:
    """Make future application database engines reject DDL."""
    global _runtime_guard_active
    _runtime_guard_active = True


def guard_runtime_engine_if_active(engine: Engine) -> None:
    if _runtime_guard_active:
        install_runtime_ddl_guard(engine)
