"""Desktop installer packaging policy checks."""

from __future__ import annotations

import json
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

    assert "Required desktop frontend asset missing" in spec
    assert '"templates" / "vue-dist" / "index.html"' in spec
    assert "PyInstaller output missing desktop frontend" in ps_backend
    assert "PyInstaller output missing desktop frontend" in sh_backend


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
    assert "Invoke-Check 'spa-home'" in smoke
    assert "expected=$ExpectedVersion" in smoke
    assert "[string]$BaseUrl = 'http://127.0.0.1:17500'" in acceptance
    assert "!isDesktopShell()" in router
    assert "profile.isAdminAccount" in router
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


def test_desktop_security_gate_cannot_synthesize_green_reports() -> None:
    workflow = (REPO_ROOT.parent / ".github" / "workflows" / "desktop-security-scan.yml").read_text(
        encoding="utf-8"
    )
    scanner = (REPO_ROOT / "desktop" / "scripts" / "security-scan.sh").read_text(encoding="utf-8")

    assert "bash scripts/security-scan.sh" in workflow
    assert "ELECTRONEGATIVITY_REPORT_DIR: /tmp/en-report" in workflow
    assert "issue, severity, confidence, filename" not in workflow
    assert "|| code=$?" not in workflow
    assert "refusing an empty false-green report" in scanner
    assert "run_with_timeout" in scanner
    assert "timeout: { request: 15000 }" in scanner


def test_desktop_electron_and_ci_node_toolchain_are_supported() -> None:
    package = json.loads((REPO_ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert package["devDependencies"]["electron"] == "41.10.1"
    assert package["devDependencies"]["cross-env"].startswith("^10.")
    assert package["engines"]["node"] == ">=22.12.0"
    assert "copyFileSync" in package["scripts"]["build"]
    assert "&& cp " not in package["scripts"]["build"]
    assert package["scripts"]["test"].startswith("cross-env XCAGI_DESKTOP_TEST=1 ")
    assert package["scripts"]["test:watch"].startswith("cross-env XCAGI_DESKTOP_TEST=1 ")
    assert package["scripts"]["test:coverage"].startswith("cross-env XCAGI_DESKTOP_TEST=1 ")

    workflows = [
        REPO_ROOT.parent / ".github" / "workflows" / "desktop-security-scan.yml",
        REPO_ROOT.parent / ".github" / "workflows" / "desktop-macos-smoke.yml",
        REPO_ROOT.parent / ".github" / "workflows" / "desktop-startup-baseline.yml",
        REPO_ROOT.parent / ".github" / "workflows" / "fhd-release-desktop.yml",
        REPO_ROOT / ".github" / "workflows" / "release-desktop.yml",
    ]
    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        assert 'node-version: "20"' not in content
        assert 'node-version: "22.12.0"' in content


def test_windows_formal_release_requires_authenticode_signing() -> None:
    build_script = (REPO_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(
        encoding="utf-8"
    )
    verify_script = (REPO_ROOT / "scripts" / "package" / "verify-windows-signature.ps1").read_text(
        encoding="utf-8"
    )
    workflows = [
        REPO_ROOT.parent / ".github" / "workflows" / "fhd-release-desktop.yml",
        REPO_ROOT / ".github" / "workflows" / "release-desktop.yml",
    ]

    assert "XCAGI_REQUIRE_WINDOWS_SIGNING" in build_script
    assert "azureSignOptions.endpoint" in build_script
    assert "Get-AuthenticodeSignature" in verify_script
    assert "Status -ne 'Valid'" in verify_script
    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        assert 'XCAGI_REQUIRE_WINDOWS_SIGNING: "1"' in content
        assert "AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE" in content
        assert "verify-windows-signature.ps1" in content


def test_frontend_uses_patched_echarts_with_modular_types() -> None:
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    tsconfig = json.loads((REPO_ROOT / "frontend" / "tsconfig.json").read_text(encoding="utf-8"))

    assert package["dependencies"]["echarts"] == "^6.1.0"
    paths = tsconfig["compilerOptions"]["paths"]
    for module in ("core", "charts", "components", "renderers"):
        assert paths[f"echarts/{module}"] == [f"./node_modules/echarts/types/dist/{module}.d.ts"]


def test_modstore_desktop_shell_uses_supported_electron() -> None:
    shell_root = REPO_ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy" / "desktop-shell"
    package = json.loads((shell_root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((shell_root / "package-lock.json").read_text(encoding="utf-8"))

    assert package["devDependencies"]["electron"] == "41.10.1"
    assert package["engines"]["node"] == ">=22.12.0"
    assert lock["packages"][""]["devDependencies"]["electron"] == "41.10.1"
    assert lock["packages"]["node_modules/electron"]["version"] == "41.10.1"


def test_mutable_update_metadata_is_never_immutably_cached() -> None:
    corp_root = REPO_ROOT.parent / "成都修茈科技有限公司"
    configs = [
        corp_root / "nginx-xiu-ci-root.conf",
        corp_root / "nginx-xiu-ci.conf",
        corp_root / "deploy" / "nginx" / "snippets" / "xcagi-cos-alias.inc.conf",
    ]
    binary_location = r"location ~* ^/releases/stable/(.+\.(?:exe|dmg|pkg|zip|blockmap))$"
    metadata_cache = 'add_header Cache-Control "no-cache, no-store, must-revalidate" always;'

    for config in configs:
        content = config.read_text(encoding="utf-8")
        assert binary_location in content
        assert metadata_cache in content

    repair_script = (REPO_ROOT.parent / "ops" / "fix-update-xcagi-https.sh").read_text(
        encoding="utf-8"
    )
    assert r"location ~* /latest(?:-mac)?\.yml$" in repair_script
    assert r"\.(exe|dmg|pkg|zip|blockmap|yml)$" not in repair_script
