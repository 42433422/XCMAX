"""Freeze the runtime ``ensure_*`` schema-patch surface (Level 2 / L2.1).

Alembic is the schema SSOT for DATABASE_URL-backed DBs. ``FHD_SKIP_ALEMBIC=1`` is
blocked at the container entrypoint unless ``FHD_ALLOW_SKIP_ALEMBIC_EMERGENCY=1``.
The squashed Alembic baseline is itself a ``Base.metadata.create_all`` snapshot, so
the ORM models *are* the Alembic schema. As long as the runtime ``ensure_*`` layer
can mint a column the ORM does not declare, the schema has two heads and Alembic can
never become the single source of truth. These guards cap that second head at zero
growth:

1. ``test_ensure_star_introduces_no_orm_absent_column`` — functional. Build a fresh
   SQLite DB via ``create_all`` (== the Alembic baseline), then run every
   column-patching ``ensure_*`` function. NOT ONE of them may add a column the ORM
   does not already declare. ``ensure_*`` may only back-fill ORM-known columns into
   pre-existing databases; it may never be a second place to grow the schema.

   => Add a column to an ``ensure_*`` function without also adding it to the ORM
      model (and therefore to the Alembic baseline) and this test goes red. The fix
      is to add the column to the ORM model + an Alembic migration, not here.

2. ``test_no_new_add_column_callsites`` — static. The set of ``init_db`` functions
   that emit ``ALTER TABLE ... ADD COLUMN`` is frozen (only-shrink). A brand-new
   column-patching function — which guard 1 would not know to invoke — still trips
   this guard, forcing the author to route the change through Alembic or to
   consciously enlist the function in this freeze.

3. ``test_ensure_emitted_columns_frozen`` — static, column-level. Guards 1 and 2
   leave one gap: editing an *already-frozen* function to ALTER in a new column and
   declaring it on the ORM too passes both (the function name is unchanged; the
   column is ORM-known). This guard freezes the exact set of column *names* the
   ``ensure_*``/``init_*`` layer can mint (only-shrink), so growing an existing
   function's column list goes red. New columns must reach the schema through an
   Alembic migration + ORM model — the ensure_* surface may only shrink.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every ORM table on Base.metadata)
from app.db import init_db
from app.db.base import Base

INIT_DB_PATH = Path(init_db.__file__)


def _runtime_source_paths() -> tuple[Path, ...]:
    """Scan live implementation modules, including any legacy re-export chain.

    Scanning only the public entry file silently passed when it became a facade.
    The whole semantic bootstrap package is covered even before a new helper is
    wired up. Historical migration-owned steps have a separate ownership guard.
    """
    pending = [INIT_DB_PATH, *sorted((INIT_DB_PATH.parent / "bootstrap").glob("*.py"))]
    found: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app.db.init_db"
            ):
                dependency = INIT_DB_PATH.parent / f"{node.module.rsplit('.', 1)[-1]}.py"
                if dependency.exists() and dependency not in found:
                    pending.append(dependency)
    return tuple(sorted(found))


def _runtime_functions(paths: tuple[Path, ...] | None = None):
    for path in _runtime_source_paths() if paths is None else paths:
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node


def _is_column_ddl(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(re.search(r"ADD\s+COLUMN", node.value, re.IGNORECASE))
    if isinstance(node, ast.Call):
        name = (
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        )
        return name in {
            "add_column",
            "batch_alter_table",
            "AddColumn",
            "AddColumnOp",
            "Column",
            "CreateColumn",
        }
    return False


def _adds_columns(node: ast.AST) -> bool:
    return any(_is_column_ddl(child) for child in ast.walk(node))


def _schema_owners(paths: tuple[Path, ...] | None = None) -> set[str]:
    owners: set[str] = set()

    def visit(node: ast.AST, owner: str = "<module data>") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node.name
        if _is_column_ddl(node):
            owners.add(owner)
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    for path in _runtime_source_paths() if paths is None else paths:
        visit(ast.parse(path.read_text(encoding="utf-8")))
    return owners


# Column-patching ``ensure_*`` functions exercised by guard 1. Each accepts
# ``engine=`` and ALTERs any missing columns into already-existing ORM tables.
ENSURE_COLUMN_PATCHERS = (
    "ensure_sessions_market_access_token_column",
    "ensure_sessions_market_refresh_token_column",
    "ensure_sessions_enterprise_entitlement_columns",
    "ensure_sessions_account_meta_columns",
    "ensure_users_tenant_id_column",
    "ensure_business_tenant_id_columns",
    "ensure_user_profile_columns",
)

# The complete, frozen surface of ``init_db`` functions that emit ``ADD COLUMN``.
# Only-shrink: removing one (because its columns migrated to Alembic) is fine;
# adding one is a deliberate decision that must update this set and, if it patches
# ORM tables, ENSURE_COLUMN_PATCHERS above. ``init_template_tables`` /
# ``init_approval_tables`` patch non-ORM (raw-SQL / PG-DDL) tables and so are not
# exercised by the functional guard.
FROZEN_ADD_COLUMN_FUNCS = frozenset(
    {
        "ensure_business_tenant_id_columns",
        "ensure_sessions_account_meta_columns",
        "ensure_sessions_enterprise_entitlement_columns",
        "ensure_sessions_market_access_token_column",
        "ensure_sessions_market_refresh_token_column",
        "ensure_user_profile_columns",
        "ensure_users_tenant_id_column",
        "init_approval_tables",
        "init_template_tables",
    }
)

# Eagerly consume the optional ``IF NOT EXISTS`` clause; the trailing ``(\w+)`` then
# captures the column. SQL keywords are filtered so the ``{name}``-interpolated
# PostgreSQL f-strings (column is a runtime value, absent from the literal) do not
# capture "IF" as a phantom column.
_ADD_COLUMN_COL_RE = re.compile(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_SQL_KEYWORDS = {"if", "not", "exists"}

# The frozen set of column names the runtime ``ensure_*``/``init_*`` layer may mint.
# ONLY-SHRINK: when a column graduates to an Alembic migration, prune it here; a NEW
# name appearing means the second schema head grew — route it through Alembic + the
# ORM model instead. Derived from init_db.py via ``_emitted_columns`` below.
FROZEN_EMITTED_COLUMNS = frozenset(
    {
        "account_kind",
        "account_tier",
        "action",
        "analyzed_data",
        "budget_range",
        "business_rules",
        "business_type",
        "company_brand",
        "created_at",
        "editable_config",
        "email_verified",
        "entitled_industries",
        "entitled_mod_ids_json",
        "failed_login_attempts",
        "impersonating_market_user_id",
        "impersonating_username",
        "industry_id",
        "is_active",
        "locked_until",
        "market_access_token",
        "market_is_admin",
        "market_is_enterprise",
        "market_membership_tier",
        "market_refresh_token",
        "market_user_id",
        "merged_cells_config",
        "original_file_path",
        "result",
        "style_config",
        "template_id",
        "template_key",
        "template_name",
        "template_type",
        "tenant_id",
        "tier",
        "updated_at",
        "zone_config",
    }
)


def _emitted_columns(func_node: ast.AST) -> set[str]:
    """Column names a frozen ``ensure_*``/``init_*`` function can ALTER into the schema.

    Two emission shapes appear in init_db.py: (a) the column literal sits inside the
    ``ALTER TABLE ... ADD COLUMN <col>`` string (incl. f-string literal parts and
    adjacent-string concatenation), and (b) ``additions = [(name, type, default), ...]``
    lists whose first tuple element is interpolated into an ``ADD COLUMN {name}`` f-string.
    """
    cols: set[str] = set()
    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            cols.update(
                m.lower()
                for m in _ADD_COLUMN_COL_RE.findall(sub.value)
                if m.lower() not in _SQL_KEYWORDS
            )
        elif isinstance(sub, (ast.List, ast.Tuple, ast.Set)):
            for elt in sub.elts:
                if isinstance(elt, ast.Tuple) and elt.elts:
                    first = elt.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        cols.add(first.value.lower())
    return cols


def _fresh_orm_engine():
    """A fresh in-memory SQLite DB built from the ORM (== the Alembic baseline)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _schema(engine) -> dict[str, set[str]]:
    insp = inspect(engine)
    return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}


def test_ensure_star_introduces_no_orm_absent_column() -> None:
    orm_schema = _schema(_fresh_orm_engine())

    patched_engine = _fresh_orm_engine()
    for name in ENSURE_COLUMN_PATCHERS:
        getattr(init_db, name)(engine=patched_engine)
    patched_schema = _schema(patched_engine)

    orm_absent = sorted(
        f"{table}.{col}"
        for table, cols in patched_schema.items()
        for col in cols - orm_schema.get(table, set())
    )

    assert orm_absent == [], (
        "ensure_*/init_db patched in column(s) the ORM does not declare, so Alembic "
        "is no longer the single source of truth for the schema:\n  "
        + "\n  ".join(orm_absent)
        + "\nAdd these columns to the ORM model (and an Alembic migration), not to an "
        "ensure_* function."
    )


def test_no_new_add_column_callsites() -> None:
    found = _schema_owners()

    new = sorted(found - FROZEN_ADD_COLUMN_FUNCS)

    assert not new, (
        "New init_db function(s) emit `ALTER TABLE ... ADD COLUMN`, growing the "
        "runtime schema-patch surface that competes with Alembic as the schema "
        f"single source of truth: {new}.\n"
        "Route new columns through an Alembic migration + ORM model. If a function "
        "genuinely only back-fills an ORM-declared column into old databases, add it "
        "to FROZEN_ADD_COLUMN_FUNCS (and, for ORM tables, ENSURE_COLUMN_PATCHERS)."
    )


def test_ensure_emitted_columns_frozen() -> None:
    live: set[str] = set()
    for node in _runtime_functions():
        if node.name in FROZEN_ADD_COLUMN_FUNCS:
            live |= _emitted_columns(node)

    grew = sorted(live - FROZEN_EMITTED_COLUMNS)

    assert not grew, (
        "ensure_*/init_db grew the runtime schema-patch surface with new column(s): "
        f"{grew}.\n"
        "The ensure_* layer is the schema's second head and may only SHRINK — route "
        "new columns through an Alembic migration + ORM model. If a column genuinely "
        "only back-fills an ORM-declared column into legacy DBs, add it to "
        "FROZEN_EMITTED_COLUMNS deliberately."
    )


def test_freeze_scanner_reaches_class_methods_and_alembic_operations(tmp_path) -> None:
    source = tmp_path / "new_schema_owner.py"
    source.write_text(
        "HIDDEN_DDL = 'ALTER TABLE users ADD COLUMN outside TEXT'\n"
        "class HiddenPatch:\n"
        "    def raw(self):\n"
        "        return 'ALTER TABLE users ADD COLUMN surprise TEXT'\n"
        "    def operation(self, operations):\n"
        "        operations.add_column('users', column)\n",
        encoding="utf-8",
    )
    assert {node.name for node in _runtime_functions((source,)) if _adds_columns(node)} == {
        "raw",
        "operation",
    }
    assert _schema_owners((source,)) == {"<module data>", "raw", "operation"}
    assert any(_adds_columns(node) for node in _runtime_functions()), (
        "Runtime DDL scan became vacuous"
    )


def test_im_provenance_is_owned_by_its_existing_revision() -> None:
    """The historical exception is a shared migration step, never a new runtime patch."""
    revision_path = (
        INIT_DB_PATH.parents[2] / "alembic" / "versions" / "2026_08_31_enterprise_cs_ai.py"
    )
    adapter_path = INIT_DB_PATH.parent / "bootstrap" / "im_migration.py"
    owner = "app.db.schema_migrations.im_message_provenance"
    for path in (revision_path, adapter_path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == owner
            and any(alias.name == "apply_message_provenance" for alias in node.names)
            for node in ast.walk(tree)
        ), f"{path.name} must reuse the historical migration owner"
        assert (
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "apply_message_provenance"
                for node in ast.walk(tree)
            )
            == 1
        )
    upgrade = next(
        node
        for node in ast.parse(revision_path.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    inline_columns = {
        node.args[0].value
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Column"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert not {"origin", "operator_user_id"} & inline_columns
