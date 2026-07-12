"""Desktop installer packaging policy checks."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_desktop_enterprise_installer_builds_full_frontend() -> None:
    scripts = REPO_ROOT / "scripts" / "package"
    ps_backend = (scripts / "build-backend.ps1").read_text(encoding="utf-8")
    ps_sync = (scripts / "sync-desktop-frontend.ps1").read_text(encoding="utf-8")
    sh_backend = (scripts / "build-backend.sh").read_text(encoding="utf-8")
    sh_windows = (scripts / "build-windows-installer.sh").read_text(encoding="utf-8")
    sh_thin = (scripts / "build-windows-electron-only.sh").read_text(encoding="utf-8")
    spec = (scripts / "xcagi_backend.spec").read_text(encoding="utf-8")

    assert "personal = 'minimal'" in ps_backend
    assert "enterprise = 'full'" in ps_backend
    assert "personal   = 'minimal'" in ps_sync
    assert "enterprise = 'full'" in ps_sync

    for script in (sh_backend, sh_windows, sh_thin):
        assert (
            "VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full npm run build:full"
        ) in script
        assert "VITE_XCAGI_PRODUCT_SKU=enterprise npm run build" not in script
        # 桌面包不得构建 admin-console
        assert "admin-console && npm run build" not in script
        assert "(cd admin-console && npm run build)" not in script

    assert "admin-console" not in ps_backend or "不构建 admin-console" in ps_backend
    assert "Push-Location (Join-Path $Root \"admin-console\")" not in ps_backend
    assert "templates/admin-vue-dist" not in spec
    assert "admin-console" not in ps_sync
    assert "does not include admin-vue-dist" in ps_sync

def test_desktop_windows_runtime_matches_mac_shell_policy() -> None:
    desktop_main = (REPO_ROOT / "desktop" / "main.ts").read_text(encoding="utf-8")
    ps_installer = (REPO_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(
        encoding="utf-8"
    )
    sh_installer = (REPO_ROOT / "scripts" / "package" / "build-windows-installer.sh").read_text(
        encoding="utf-8"
    )
    smoke = (REPO_ROOT / "scripts" / "package" / "smoke-installed-windows.ps1").read_text(
        encoding="utf-8"
    )
    acceptance = (REPO_ROOT / "scripts" / "package" / "acceptance-sunbird-windows.ps1").read_text(
        encoding="utf-8"
    )
    router = (REPO_ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "scripts" / "package" / "xcagi_backend.spec").read_text(encoding="utf-8")

    assert "return 17500" in desktop_main
    assert "process.platform === 'darwin' ? 17500 : 5000" not in desktop_main
    assert '"return 17500"' in ps_installer
    assert '"return 17500"' in sh_installer
    assert '"backendHealthMs"' in ps_installer
    assert '"backendHealthMs"' in sh_installer
    assert "[string]$BaseUrl = 'http://127.0.0.1:17500'" in smoke
    assert "[string]$BaseUrl = 'http://127.0.0.1:17500'" in acceptance
    assert "isDesktopShell" in router
    # 网页 admin → /admin；桌面壳 admin → 拒入（管理端仅网页 SSOT）
    assert "resolveAdminConsoleHomeUrl()" in router
    assert "profile.isAdminAccount" in router
    assert "DESKTOP_ADMIN_FORBIDDEN_MESSAGE" in router
    assert "next({ name: 'chat', replace: true });" not in router
    assert "console=False" in spec


def test_missing_industry_seed_does_not_block_desktop_release() -> None:
    scripts = REPO_ROOT / "scripts" / "package"
    ps_stage = (scripts / "stage-industry-seeds.ps1").read_text(encoding="utf-8")
    sh_stage = (scripts / "stage-industry-seeds.sh").read_text(encoding="utf-8")
    ps_verify = (scripts / "verify-industry-seeds.ps1").read_text(encoding="utf-8")

    assert "Skipped missing industry seed mod(s)" in ps_stage
    assert "Skipped missing industry seed mod(s)" in sh_stage
    assert "Skipped missing industry seed mod(s)" in ps_verify
    assert 'throw "Missing industry seed mod(s)' not in ps_stage
    assert 'throw "industry-seeds/ missing open industry mod(s)' not in ps_verify
    assert "exit 1" not in sh_stage.split("Skipped missing industry seed mod(s)", 1)[-1]
