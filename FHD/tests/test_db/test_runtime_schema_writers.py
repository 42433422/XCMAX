from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.schema_contract import RuntimeSchemaMutationForbidden, install_runtime_ddl_guard

LEGACY_PRIMARY_SCHEMA_WRITERS = {
    "init_approval_tables",
    "init_distillation_tables",
    "init_extract_logs_tables",
    "init_im_tables",
    "init_persona_tables",
    "init_service_bridge_tables",
    "init_template_tables",
    "init_template_tables_for_engine",
    "init_wechat_tasks_table",
    "ensure_ai_conversation_bootstrap",
    "ensure_business_tenant_id_columns",
    "ensure_employee_run_log_bootstrap",
    "ensure_mobile_push_bootstrap",
    "ensure_neuro_event_log_bootstrap",
    "ensure_postgresql_auth_bootstrap",
    "ensure_product_query_indexes",
    "ensure_runtime_auth_bootstrap",
    "ensure_sessions_account_meta_columns",
    "ensure_sessions_enterprise_entitlement_columns",
    "ensure_sessions_market_access_token_column",
    "ensure_sessions_market_refresh_token_column",
    "ensure_sqlite_auth_bootstrap",
    "ensure_sqlite_enterprise_business_bootstrap",
    "ensure_sqlite_im_bootstrap",
    "ensure_sqlite_inventory_bootstrap",
    "ensure_sqlite_rbac_bootstrap",
    "ensure_user_preferences_bootstrap",
    "ensure_user_profile_columns",
    "ensure_users_tenant_id_column",
}


def test_runtime_code_does_not_call_legacy_primary_schema_writers() -> None:
    """Legacy DDL helpers may serve tests/tools, but application paths cannot call them."""
    app_root = Path(__file__).resolve().parents[2] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        if path.as_posix().endswith("app/db/init_db.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in LEGACY_PRIMARY_SCHEMA_WRITERS
            ):
                offenders.append(f"{path.relative_to(app_root)}:{node.lineno}:{node.func.id}")

    assert offenders == [], (
        "runtime code reintroduced the legacy create_all/ensure_* schema head: "
        + ", ".join(offenders)
    )


def test_primary_runtime_services_contain_no_ddl_or_create_all() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    primary_runtime_modules = (
        "app/application/agent_orchestrator/run_repository.py",
        "app/application/im_app_service.py",
        "app/services/ai_action_audit_service.py",
        "app/services/mobile_relay_service.py",
    )
    offenders: list[str] = []
    for relative in primary_runtime_modules:
        source = (repo_root / relative).read_text(encoding="utf-8")
        upper = source.upper()
        if any(token in upper for token in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE")):
            offenders.append(f"{relative}:DDL")
        if ".create_all(" in source:
            offenders.append(f"{relative}:create_all")
    assert offenders == []


def test_runtime_ddl_guard_rejects_schema_mutation() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_runtime_ddl_guard(engine)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        with pytest.raises(RuntimeSchemaMutationForbidden):
            connection.execute(text("CREATE TABLE forbidden_runtime_table (id INTEGER)"))
