from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]


def test_per_user_nsis_installer_does_not_enter_uac_plugin_path() -> None:
    config = yaml.safe_load(
        (FHD_ROOT / "desktop" / "electron-builder.yml").read_text(encoding="utf-8")
    )
    nsis = config["nsis"]

    assert nsis["perMachine"] is False
    assert nsis["allowElevation"] is False
    assert nsis["allowToChangeInstallationDirectory"] is True


def test_installer_cleans_only_the_known_legacy_uninstall_entry() -> None:
    installer = (FHD_ROOT / "desktop" / "build" / "installer.nsh").read_text(encoding="utf-8")

    assert "6f93bd19-4cab-50af-bfb3-b3aea3badc52" in installer
    assert 'DisplayVersion"' in installer
    assert '$1 == "8.0.0"' in installer
    assert "DeleteRegKey HKCU" in installer


def test_backup_task_uses_native_recurring_triggers_and_action_arguments() -> None:
    script = (FHD_ROOT / "scripts" / "backup" / "Install-BackupTask.ps1").read_text(
        encoding="utf-8"
    )

    assert "New-ScheduledTaskTrigger -Daily -At $At" in script
    assert "New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $At" in script
    assert "-Argument $ActionArguments" in script
    assert '$CmdLine = "powershell.exe "' not in script
    assert "[datetime]$Trigger" not in script


def test_packaged_backup_powershell_scripts_are_windows_5_utf8_safe() -> None:
    backup_dir = FHD_ROOT / "scripts" / "backup"

    for script in backup_dir.glob("*.ps1"):
        assert script.read_bytes().startswith(b"\xef\xbb\xbf"), script.name


def test_backup_script_does_not_bind_path_array_as_join_path_child_path() -> None:
    script = (FHD_ROOT / "scripts" / "backup" / "XcagiBackup.ps1").read_text(encoding="utf-8-sig")

    assert '    (Join-Path $env:LOCALAPPDATA "Programs\\XCAGI' in script
    assert '    Join-Path $env:LOCALAPPDATA "Programs\\XCAGI' not in script
    assert "-WorkingDirectory $backendDir" in script


def test_windows_build_identity_records_an_orderable_timestamp() -> None:
    script = (FHD_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(encoding="utf-8")

    assert "schema_version = 2" in script
    assert "builtAt = (Get-Date).ToUniversalTime().ToString('o')" in script
    assert "[System.IO.File]::WriteAllText($buildInfoPath" in script
    assert "Set-Content -Path $buildInfoPath -Encoding UTF8" not in script


def test_windows_build_verifies_the_packaged_runtime_dependency_graph() -> None:
    script = (FHD_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(encoding="utf-8")

    assert "verify-packaged-runtime.cjs" in script
    assert "Electron packaged runtime dependency verification failed" in script


def test_windows_build_uses_clean_checked_node_installs() -> None:
    installer = (FHD_ROOT / "scripts" / "package" / "build-installer.ps1").read_text(
        encoding="utf-8"
    )
    backend = (FHD_ROOT / "scripts" / "package" / "build-backend.ps1").read_text(encoding="utf-8")

    assert "npm ci --include=dev" in installer
    assert "desktop npm ci failed" in installer
    assert "Desktop TypeScript compiler" in installer
    assert "npm ci --include=dev" in backend
    assert "frontend npm ci failed" in backend
    assert "frontend npm build failed" in backend
