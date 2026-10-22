from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
HELPER = FHD_ROOT / "scripts/deploy/lib/apply_recovery.sh"
GIT_SHA = "a" * 40
ADMIN_SHA = "b" * 64


def _source_call(*parts: str) -> subprocess.CompletedProcess[str]:
    script = f"source {shlex.quote(str(HELPER))}; " + " ".join(shlex.quote(p) for p in parts)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


def _old_anchor(root: Path, backup: Path) -> dict[str, bytes]:
    values = {
        ".deploy-last.tar.gz": b"previous-archive",
        ".deploy-sha256": (hashlib.sha256(b"previous-archive").hexdigest() + "\n").encode(),
        ".deploy-git-sha": ("c" * 40 + "\n").encode(),
        ".deploy-admin-console-sha256": ("d" * 64 + "\n").encode(),
    }
    root.mkdir()
    backup.mkdir()
    for name, payload in values.items():
        (root / name).write_bytes(payload)
        shutil.copy2(root / name, backup / name)
    return values


def test_identity_transaction_commits_archive_and_stamps_as_a_verified_set(tmp_path: Path) -> None:
    root, backup = tmp_path / "deploy", tmp_path / "backup"
    _old_anchor(root, backup)
    archive = tmp_path / "candidate.tar.gz"
    archive.write_bytes(b"candidate-release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    result = _source_call(
        "fhd_commit_release_identity",
        str(archive),
        str(root),
        str(backup),
        digest,
        GIT_SHA,
        ADMIN_SHA,
    )
    assert result.returncode == 0, result.stderr
    assert (root / ".deploy-identity-pending").is_file()
    assert (backup / ".deploy-identity-pending").is_file()

    result = _source_call(
        "fhd_complete_release_identity", str(root), str(backup), digest, GIT_SHA, ADMIN_SHA
    )
    assert result.returncode == 0, result.stderr
    assert hashlib.sha256((root / ".deploy-last.tar.gz").read_bytes()).hexdigest() == digest
    assert (root / ".deploy-sha256").read_text().strip() == digest
    assert (root / ".deploy-git-sha").read_text().strip() == GIT_SHA
    assert (root / ".deploy-admin-console-sha256").read_text().strip() == ADMIN_SHA
    assert not (root / ".deploy-identity-pending").exists()
    assert not (backup / ".deploy-identity-pending").exists()


def test_failed_partial_identity_replace_retains_and_restores_old_anchor(tmp_path: Path) -> None:
    root, backup = tmp_path / "deploy", tmp_path / "backup"
    old = _old_anchor(root, backup)
    archive = tmp_path / "candidate.tar.gz"
    archive.write_bytes(b"candidate-release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    # Simulate an OS rename failure after archive/SHA/Git replacements but before admin stamp.
    (root / ".deploy-admin-console-sha256").unlink()
    (root / ".deploy-admin-console-sha256").mkdir()

    result = _source_call(
        "fhd_commit_release_identity",
        str(archive),
        str(root),
        str(backup),
        digest,
        GIT_SHA,
        ADMIN_SHA,
    )
    assert result.returncode != 0
    assert (root / ".deploy-identity-pending").is_file()
    assert (backup / ".deploy-identity-pending").is_file()
    assert (root / ".deploy-last.tar.gz").read_bytes() == b"candidate-release"
    assert (backup / ".deploy-last.tar.gz").read_bytes() == old[".deploy-last.tar.gz"]

    (root / ".deploy-admin-console-sha256").rmdir()
    result = _source_call("fhd_restore_release_identity", str(root), str(backup))
    assert result.returncode == 0, result.stderr
    for name, payload in old.items():
        assert (root / name).read_bytes() == payload
    assert not (root / ".deploy-identity-pending").exists()
    assert not (backup / ".deploy-identity-pending").exists()


def test_digest_mismatch_fails_before_pending_marker_or_identity_mutation(tmp_path: Path) -> None:
    root, backup = tmp_path / "deploy", tmp_path / "backup"
    old = _old_anchor(root, backup)
    archive = tmp_path / "candidate.tar.gz"
    archive.write_bytes(b"candidate-release")

    result = _source_call(
        "fhd_commit_release_identity",
        str(archive),
        str(root),
        str(backup),
        "0" * 64,
        GIT_SHA,
        ADMIN_SHA,
    )
    assert result.returncode != 0
    assert not (root / ".deploy-identity-pending").exists()
    for name, payload in old.items():
        assert (root / name).read_bytes() == payload


def test_recovery_and_completion_refuse_an_unrelated_backup(tmp_path: Path) -> None:
    root, backup = tmp_path / "deploy", tmp_path / "backup"
    old = _old_anchor(root, backup)
    archive = tmp_path / "candidate.tar.gz"
    archive.write_bytes(b"candidate-release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = _source_call(
        "fhd_commit_release_identity",
        str(archive),
        str(root),
        str(backup),
        digest,
        GIT_SHA,
        ADMIN_SHA,
    )
    assert result.returncode == 0, result.stderr
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = _source_call("fhd_restore_release_identity", str(root), str(unrelated))
    assert result.returncode != 0
    result = _source_call(
        "fhd_complete_release_identity", str(root), str(unrelated), digest, GIT_SHA, ADMIN_SHA
    )
    assert result.returncode != 0
    assert (root / ".deploy-identity-pending").is_file()
    assert (root / ".deploy-last.tar.gz").read_bytes() == b"candidate-release"
    result = _source_call("fhd_restore_release_identity", str(root), str(backup))
    assert result.returncode == 0, result.stderr
    assert all((root / name).read_bytes() == data for name, data in old.items())


def test_incomplete_identity_transaction_blocks_auto_update_before_sha_short_circuit() -> None:
    auto = (FHD_ROOT / "scripts/deploy/fhd-auto-update.sh").read_text(encoding="utf-8")
    freeze = auto.index('if [[ -f "$FREEZE_MARKER" ]]')
    pending = auto.index('if [[ -e "$DEPLOY_ROOT/.deploy-identity-pending" ]]')
    already_latest = auto.index('if [[ "$REMOTE_SHA" == "$LOCAL_SHA"')
    assert freeze < pending < already_latest

    pruner = (FHD_ROOT / "scripts/deploy/prune_release_cache.py").read_text(encoding="utf-8")
    assert 'not (item / ".deploy-identity-pending").is_file()' in pruner
