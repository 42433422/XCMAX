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
    assert 'Push-Location (Join-Path $Root "admin-console")' not in ps_backend
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


def test_windows_release_requires_sslcom_signing_and_system_authenticode() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    build = (REPO_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(encoding="utf-8")
    signer = (REPO_ROOT / "desktop" / "build" / "windows-sign.cjs").read_text(encoding="utf-8")
    post_gate = (REPO_ROOT / "scripts" / "package" / "pre-release-security.ps1").read_text(
        encoding="utf-8"
    )
    verifier = (REPO_ROOT / "scripts" / "package" / "verify-windows-signature.ps1").read_text(
        encoding="utf-8"
    )
    installed_runtime = (
        REPO_ROOT / "scripts" / "package" / "verify-windows-installed-runtime.ps1"
    ).read_text(encoding="utf-8")

    for name in (
        "ES_USERNAME",
        "ES_PASSWORD",
        "CREDENTIAL_ID",
        "ES_TOTP_SECRET",
    ):
        assert name in workflow
        assert name in build
        assert name in signer

    assert 'XCAGI_REQUIRE_WINDOWS_SIGNING: "1"' in workflow
    assert "XCAGI_WINDOWS_SIGNING_PROVIDER: sslcom" in workflow
    assert "SSLcom/esigner-codesign@cf5f6c1d38ad10f47e3ed9aca873f429b1a8d85b" in workflow
    assert "--config.forceCodeSigning=true" in build
    assert "--config.win.signtoolOptions.sign=build/windows-sign.cjs" in build
    assert "--config.win.signtoolOptions.signingHashAlgorithms=sha256" in build
    assert "--config.win.publisherName=" in build
    assert "AZURE_TRUSTED_SIGNING" not in workflow
    assert "AZURE_TRUSTED_SIGNING" not in build
    assert "-override=true" in signer
    assert "spawn(java, args" in signer
    assert "Get-AuthenticodeSignature -LiteralPath" in verifier
    assert "$signature.Status -ne 'Valid'" in verifier
    assert "$signature.TimeStamperCertificate" in verifier
    assert post_gate.count("verify-windows-signature.ps1") == 3
    assert "verify-windows-installed-runtime.ps1" in workflow
    assert "verify-public-windows-signature:" in workflow
    assert "Get-AuthenticodeSignature -LiteralPath $installer" in workflow
    assert "Published Windows installer is not Authenticode-valid" in workflow
    assert "verify-windows-signature.ps1 `" in workflow
    assert "-ExpectedPublisher $env:XCAGI_WINDOWS_PUBLISHER_NAME" in workflow
    assert '-ExpectedBuildSha "${{ github.sha }}"' in workflow
    assert "-ExpectedProductVersion $v" in workflow
    assert "verify-windows-signature.ps1" in installed_runtime
    assert "smoke-installed-windows.ps1" in installed_runtime
    assert "Start-Process" in installed_runtime
    assert "@('/S', \"/D=$InstallDir\")" in installed_runtime
    assert "Uninstall XCAGI.exe" in installed_runtime
    assert "Wait-PathRemoved -Path $installedExe" in installed_runtime
    assert "deleteAppDataOnUninstall must remain false" in installed_runtime


def test_desktop_release_preflights_both_platforms_and_publishes_as_one_unit() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )

    assert "release-preflight:" in workflow
    assert workflow.count("needs: [release-preflight]") == 2
    assert 'missing+=("APPLE_TEAM_ID|IOS_TEAM_ID")' in workflow
    assert 'missing+=("SERVER_SSH_KEY|FHD_PUSH_SSH_KEY")' in workflow
    assert "deploy-windows:" not in workflow
    assert "deploy-macos:" not in workflow
    assert "needs: [release-preflight, windows, macos]" in workflow
    assert "Publish unified Windows + macOS release to CVM" in workflow
    assert "publish-website-pointer:" in workflow
    assert (
        "needs: [generate-manifest, verify-download, verify-public-windows-signature]" in workflow
    )
    assert "needs.verify-public-windows-signature.result == 'success'" in workflow
    assert "--delay-updates" in workflow
    assert workflow.index('official_root="/var/www/xcagi-v${version}"') < workflow.index(
        'stable_root="/var/www/update/releases/stable"'
    )


def test_windows_release_scripts_are_parsed_on_a_real_windows_ci_runner() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")

    job = workflow.split("  desktop-windows-release-script-smoke:", 1)[1].split(
        "\n  # SSOT drift gate", 1
    )[0]
    assert "runs-on: windows-latest" in job
    assert "build-installer.ps1" in job
    assert "pre-release-security.ps1" in job
    assert "verify-windows-signature.ps1" in job
    assert "verify-windows-installed-runtime.ps1" in job
    assert "[scriptblock]::Create" in job
    assert "node --check desktop/build/windows-sign.cjs" in job
    assert "SSLcom/esigner-codesign@cf5f6c1d38ad10f47e3ed9aca873f429b1a8d85b" in job
    assert "CODE_SIGN_TOOL_PATH" in job
    assert "code_sign_tool-1.3.0.jar" in job
    assert "& $java -Xmx1024M -jar $jar --version" in job
    assert "rollback-windows.test.ts" in job
    assert "updater-install.test.ts" in job


def test_desktop_update_rollback_is_fail_closed_and_windows_full_app() -> None:
    main = (REPO_ROOT / "desktop" / "main.ts").read_text(encoding="utf-8")
    rollback = (REPO_ROOT / "desktop" / "rollback.ts").read_text(encoding="utf-8")
    windows = (REPO_ROOT / "desktop" / "rollback-windows.ts").read_text(encoding="utf-8")
    updater = (REPO_ROOT / "desktop" / "updater.ts").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "XCAGI" / "run_fastapi.py").read_text(encoding="utf-8")

    assert "继续更新但不支持回滚" not in main
    assert "cancelPreparedRollback()" in main
    assert "attachDatabaseBackupToRollback" in main
    assert "consumeRollbackApplied()" in main
    assert (
        "if (pendingRollback) {\n"
        "          await waitForMainApplicationReady()\n"
        "          await waitForPostUpdateStartupStability()\n"
        "          commitRollback()"
    ) in main
    assert "mainApplicationReady = ready" in main
    assert "POST_UPDATE_STABILITY_MS = 5_000" in main
    assert "rendererFailedDuringStartup = true" in main
    assert "throw error" in main
    assert "mode: 'windows-full'" in rollback
    assert "launchWindowsFullRollback" in rollback
    assert "windows-app-current" in rollback
    assert "Move-Item -LiteralPath $stagingDir -Destination $installDir" in windows
    assert "Copy-Item -LiteralPath $databaseBackupPath" in windows
    assert "downloadedBuildSha.slice(0, 12)" in updater
    assert "migration backup failed; refusing to continue" in entrypoint


def test_desktop_package_includes_chat_voice_runtime() -> None:
    spec = (REPO_ROOT / "scripts" / "package" / "xcagi_backend.spec").read_text(encoding="utf-8")
    build = (REPO_ROOT / "scripts" / "package" / "build-backend.sh").read_text(encoding="utf-8")
    normalizer = (
        REPO_ROOT / "scripts" / "package" / "normalize-macos-python-binaries.sh"
    ).read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    excludes = spec.split("desktop_excludes = [", 1)[1].split("]", 1)[0]
    assert '"faster_whisper"' not in excludes
    assert '"av"' not in excludes
    assert "collect_submodules(module)" in spec
    assert "collect_dynamic_libs(module)" in spec
    assert "binaries=binaries" in spec
    assert '"av>=17.1,<18"' in pyproject
    assert "normalize-macos-python-binaries.sh" in build
    assert "find \"${SITE_PACKAGES}\" -type f -name '*.dylib' -print0" in normalizer
    assert "find \"${SITE_PACKAGES}\" -type f -name '*.so' -print0" in normalizer
    assert "codesign --force --sign -" in normalizer
    assert "import av" in normalizer
    assert "import ctranslate2" in normalizer
    assert "import gevent" in normalizer


def test_macos_after_pack_uses_unambiguous_developer_id_and_fails_closed() -> None:
    after_pack = (REPO_ROOT / "desktop" / "build" / "after-pack.cjs").read_text(encoding="utf-8")

    assert "`Developer ID Application: ${fromEnv}`" in after_pack
    assert "/^[0-9a-f]{40}$/i.test(fromEnv)" in after_pack
    assert "match[2] === fullName" in after_pack
    assert "log(`native sign warn" not in after_pack


def test_desktop_package_includes_commercial_safe_pdf_runtime() -> None:
    spec = (REPO_ROOT / "scripts" / "package" / "xcagi_backend.spec").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "XCAGI" / "run_fastapi.py").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    employee_root = REPO_ROOT / "mods" / "_employees"
    employee_runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for employee_name in ("pdf-generate-employee", "pdf-full-read-employee")
        for path in (employee_root / employee_name / "backend").rglob("*.py")
    )

    assert '"pypdf>=6.14,<7"' in pyproject
    assert '"reportlab>=5,<6"' in pyproject
    assert "PyMuPDF" not in pyproject
    assert "collect_submodules(module)" in spec
    assert 'for module in ["pypdf", "reportlab"]' in spec
    assert "import fitz" not in employee_runtime
    assert "from pypdf import PdfReader" in employee_runtime
    assert "from reportlab.pdfgen import canvas" in employee_runtime
    assert "--verify-frozen-critical-runtime" in entrypoint
    assert "import faster_whisper" in entrypoint
    assert 'bundled_root = Path(sys._MEIPASS) / "mods" / "_employees"' in entrypoint
    assert "installed != bundled" in entrypoint
    assert workflow.count("--verify-frozen-critical-runtime") == 2


def test_frozen_excel_temp_files_use_writable_app_data() -> None:
    modules = [
        REPO_ROOT / "app" / "application" / "excel_template_http_app_service.py",
        REPO_ROOT / "app" / "fastapi_routes" / "excel_extract.py",
    ]

    for path in modules:
        source = path.read_text(encoding="utf-8")
        assert "get_app_data_dir" in source
        assert 'os.path.join(get_app_data_dir(), "temp_excel")' in source
        assert 'str(_REPO_ROOT / "temp_excel")' not in source

    template_service = modules[0].read_text(encoding="utf-8")
    assert "os.makedirs(TEMPLATE_DIR" not in template_service


def test_server_api_runtime_excludes_unmaintained_python_ecdsa_stack() -> None:
    """CVE-2024-23342 has no patched python-ecdsa release; PyJWT is the SSOT."""
    dependency_files = (
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "requirements.txt",
        REPO_ROOT / "deploy" / "requirements-server-api.txt",
        REPO_ROOT / "deploy" / "requirements-server-api.lock.txt",
        REPO_ROOT / "uv.lock",
    )
    for dependency_file in dependency_files:
        contents = dependency_file.read_text(encoding="utf-8").lower()
        assert "python-jose" not in contents, dependency_file
        assert 'name = "ecdsa"' not in contents, dependency_file


def test_macos_installer_reuses_clean_local_electron_distribution() -> None:
    installer = (REPO_ROOT / "scripts" / "package" / "build-installer.sh").read_text(
        encoding="utf-8"
    )
    builder = (REPO_ROOT / "desktop" / "electron-builder.yml").read_text(encoding="utf-8")
    dmg_builder = (REPO_ROOT / "scripts" / "package" / "create-mac-dmg.sh").read_text(
        encoding="utf-8"
    )
    notarize = (REPO_ROOT / "desktop" / "build" / "notarize.cjs").read_text(encoding="utf-8")
    before_pack = (REPO_ROOT / "desktop" / "build" / "before-pack.cjs").read_text(encoding="utf-8")

    assert 'xattr -cr "${DESKTOP_ELECTRON_DIST}"' in installer
    assert '"--config.electronDist=${DESKTOP_ELECTRON_DIST}"' in installer
    assert '"--config.directories.output=${package_stage}"' in installer
    assert 'for staged_file in "${package_stage}"/*' in installer
    assert 'ditto --norsrc "${staged_file}" "${out_dir}/$(basename "${staged_file}")"' in installer
    assert 'ditto --norsrc "${package_stage}" "${out_dir}"' not in installer
    assert "electron-builder --mac zip" in installer
    assert "electron-builder --mac dmg" not in installer
    assert "scripts/package/create-mac-dmg.sh" in installer
    assert "hdiutil create" in dmg_builder
    assert "notarytool submit" in dmg_builder
    assert "stapler staple" in dmg_builder
    assert "Apply signing normalization to both the local dotenv path" in installer
    assert installer.index('if [ -f "${MAC_SIGNING_ENV}" ]') < installer.index(
        'if [ -n "${CSC_LINK:-}" ]'
    )
    assert "unset CSC_LINK" in installer
    assert "SKIP_DESKTOP_BUILD=1 but desktop/dist/main.js is missing" in installer
    assert "msg.includes('abortedUpload')" in notarize
    assert "msg.includes('deadlineExceeded')" in notarize
    # Keep a dist-local manifest in the ASAR: Electron's packaged startup can
    # resolve dist/ as the app root before it loads dist/main.js.
    assert "beforePack: build/before-pack.cjs" in builder
    assert "  - dist/**" in builder
    assert "writeDesktopRuntimePackage(desktopDir)" in before_pack
    assert "path.join(distDir, 'package.json')" in before_pack
    assert "main: 'main.js'" in before_pack
    assert "desktop runtime entry is missing" in before_pack


def test_desktop_release_uses_locked_physical_dependencies_and_checks_asar_closure() -> None:
    scripts = REPO_ROOT / "scripts" / "package"
    mac_installer = (scripts / "build-installer.sh").read_text(encoding="utf-8")
    windows_installer = (scripts / "build-windows-installer.sh").read_text(encoding="utf-8")
    windows_thin = (scripts / "build-windows-electron-only.sh").read_text(encoding="utf-8")
    windows_ps = (scripts / "build-installer.ps1").read_text(encoding="utf-8")
    asar_verifier = (REPO_ROOT / "desktop" / "build" / "verify-runtime-asar.cjs").read_text(
        encoding="utf-8"
    )

    for script in (mac_installer, windows_installer, windows_thin):
        assert "desktop/node_modules must be a physical directory" in script
        assert "npm ci --no-audit --fund=false" in script
        assert "verify-runtime-asar.cjs" in script

    assert "XCAGI_ELECTRON_DIST_SOURCE" in mac_installer
    assert "npm ci --ignore-scripts --no-audit --fund=false" in mac_installer
    assert "external Electron version mismatch" in mac_installer
    assert "DESKTOP_ELECTRON_DIST" in mac_installer
    assert "ReparsePoint" in windows_ps
    assert "npm ci --no-audit --fund=false" in windows_ps
    assert "verify-runtime-asar.cjs" in windows_ps

    assert "asar.listPackage" in asar_verifier
    assert "optionalDependencies" in asar_verifier
    assert "runtime dependency is missing" in asar_verifier
    assert "findPackageManifest" in asar_verifier


def test_desktop_staging_bundles_visible_office_employee_executors() -> None:
    scripts = REPO_ROOT / "scripts" / "package"
    sh_stage = (scripts / "stage-bundled-mods.sh").read_text(encoding="utf-8")
    ps_stage = (scripts / "stage-bundled-mods.ps1").read_text(encoding="utf-8")

    for stage_script in (sh_stage, ps_stage):
        assert "office_pack_catalog.json" in stage_script
        assert "_employees" in stage_script
        assert "Missing required Office employee pack" in stage_script


def test_frozen_backend_dispatches_multiprocessing_workers_before_cli() -> None:
    entrypoint = (REPO_ROOT / "XCAGI" / "run_fastapi.py").read_text(encoding="utf-8")
    frozen_main = entrypoint.split('if __name__ == "__main__":', 1)[1]

    assert "multiprocessing.freeze_support()" in frozen_main
    assert frozen_main.index("multiprocessing.freeze_support()") < frozen_main.index("main()")


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
