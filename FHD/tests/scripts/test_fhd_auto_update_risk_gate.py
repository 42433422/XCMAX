# mypy: disable-error-code="assignment"
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = FHD_ROOT / "scripts" / "deploy" / "fhd-auto-update.sh"
AUTONOMY_BRIDGE = FHD_ROOT / "scripts" / "deploy" / "lib" / "autonomy_gate.sh"


def _runtime(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    deploy_root = tmp_path / "deploy"
    (deploy_root / ".venv" / "bin").mkdir(parents=True)
    (deploy_root / "app").symlink_to(FHD_ROOT / "app", target_is_directory=True)
    (deploy_root / "config").symlink_to(FHD_ROOT / "config", target_is_directory=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    flock = bin_dir / "flock"
    flock.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    flock.chmod(0o755)
    manifest = tmp_path / "fhd-manifest.json"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "FHD_DEPLOY_ROOT": str(deploy_root),
        "FHD_MANIFEST_PATH": str(manifest),
        "FHD_DEPLOY_LOG": str(tmp_path / "deploy.log"),
        "FHD_AUTO_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "FHD_AUTONOMY_PYTHON": sys.executable,
        "XCAGI_AUTONOMY_DATA_DIR": str(tmp_path / "autonomy"),
        "XCAGI_AUTONOMY_AUDIT_LOG_PATH": str(tmp_path / "autonomy" / "autonomy-audit-log.jsonl"),
    }
    return deploy_root, manifest, env


def test_deploy_bridge_hard_blocks_prohibited_migration(tmp_path: Path) -> None:
    deploy_root = tmp_path / "deploy"
    deploy_root.mkdir()
    (deploy_root / "app").symlink_to(FHD_ROOT / "app", target_is_directory=True)
    (deploy_root / "config").symlink_to(FHD_ROOT / "config", target_is_directory=True)
    data_dir = tmp_path / "autonomy"
    command = f". {AUTONOMY_BRIDGE!s}; autonomy_evaluate_action db_migration migration:test-bridge"
    result = subprocess.run(
        ["bash", "-c", command],
        env={
            **os.environ,
            "FHD_DEPLOY_ROOT": str(deploy_root),
            "FHD_AUTONOMY_PYTHON": sys.executable,
            "XCAGI_AUTONOMY_DATA_DIR": str(data_dir),
            "XCAGI_AUTONOMY_AUDIT_LOG_PATH": str(data_dir / "autonomy-audit-log.jsonl"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    audit = (data_dir / "autonomy-audit-log.jsonl").read_text(encoding="utf-8")
    assert '"action": "db_migration"' in audit
    assert '"decision": "prohibited"' in audit


def _manifest(*, approved: bool) -> dict:
    doc = {
        "artifact": "missing.tar.gz",
        "channel": "stable",
        "deploy_mode": "tarball",
        "git_sha": "abc123",
        "sha256": "0" * 64,
        "admin_console_sha256": "1" * 64,
        "version": "test",
    }
    if approved:
        doc["autonomy_approval"] = {
            "approved_by": "reviewer",
            "approval_id": "run-1",
            "environment": "production",
            "source": "github_environment",
        }
    return doc


def test_stable_auto_update_requires_human_approval(tmp_path: Path) -> None:
    _, manifest, env = _runtime(tmp_path)
    manifest.write_text(json.dumps(_manifest(approved=False)), encoding="utf-8")
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    assert result.returncode == 77
    log = (tmp_path / "deploy.log").read_text(encoding="utf-8")
    assert "autonomy_guard 拒绝稳定通道发布" in log
    assert "artifact 不存在" not in log


def test_auto_update_and_deploy_bridge_have_no_human_approval_dependency() -> None:
    auto_update = SCRIPT.read_text(encoding="utf-8")
    bridge = AUTONOMY_BRIDGE.read_text(encoding="utf-8")

    for source in (auto_update, bridge):
        assert "FHD_AUTONOMY_APPROVED_BY" not in source
        assert "FHD_AUTONOMY_APPROVAL_ID" not in source
        assert '"human_approved"' not in source
        assert '"approved_by"' not in source
    assert "autonomy_approval" not in auto_update


def test_auto_update_prefers_bundled_dr_sync_for_immutable_release(
    tmp_path: Path,
) -> None:
    deploy_root, manifest, env = _runtime(tmp_path)
    sync_script = deploy_root / "scripts" / "deploy" / "xcmax-release-sync.sh"
    sync_script.parent.mkdir(parents=True)
    sync_script.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$SYNC_MARKER"\n',
        encoding="utf-8",
    )
    sync_script.chmod(0o755)
    marker = tmp_path / "sync-marker"
    artifact_sha = "0" * 64
    git_sha = "a" * 40
    (deploy_root / ".deploy-sha256").write_text(artifact_sha, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "admin_console_sha256": "1" * 64,
                "artifact": "already-live.tar.gz",
                "channel": "stable",
                "deploy_mode": "tarball",
                "git_sha": git_sha,
                "sha256": artifact_sha,
                "version": "test",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**env, "SYNC_MARKER": str(marker)},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8").strip() == (f"--component fhd --sha {git_sha}")


def test_stable_auto_update_rejects_untrusted_manifest_approval(tmp_path: Path) -> None:
    _, manifest, env = _runtime(tmp_path)
    manifest.write_text(json.dumps(_manifest(approved=True)), encoding="utf-8")
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    assert result.returncode == 77
    log = (tmp_path / "deploy.log").read_text(encoding="utf-8")
    assert "autonomy_guard 拒绝稳定通道发布" in log
    assert "artifact 不存在" not in log
