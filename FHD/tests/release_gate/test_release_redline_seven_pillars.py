"""发版红线静态断言（release_gate 子集，无重依赖 import）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_auth_permission_resolver_exists():
    # Compat shim may live at application/; canonical implementation at domain/app_pure/.
    shim = ROOT / "app/application/auth_permission_resolver.py"
    canonical = ROOT / "app/domain/app_pure/auth_permission_resolver.py"
    assert shim.is_file()
    text = (
        canonical.read_text(encoding="utf-8")
        if canonical.is_file()
        else shim.read_text(encoding="utf-8")
    )
    assert "def resolve_permissions" in text
    assert "enterprise_viewer" in text


def test_release_verify_script_exists():
    script = ROOT / "scripts/dev/release_verify.sh"
    assert script.is_file()
    body = script.read_text(encoding="utf-8")
    assert "npm run type-check" in body
    assert "npm run build:strict" in body


def test_office_platform_routes_registered():
    routes = (ROOT / "app/fastapi_routes/platform_shell_routes.py").read_text(encoding="utf-8")
    assert "workspace-read-files" in routes
    assert "onboarding/seed-demo" in routes
    assert "office/confirm" in routes


def test_employee_run_log_migration_present():
    migration = ROOT / "alembic/versions/2026_07_05_employee_run_logs.py"
    assert migration.is_file()
    assert "employee_run_logs" in migration.read_text(encoding="utf-8")
