from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

FHD_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = FHD_ROOT / "scripts/deploy/lib/verify_release_archive.py"
REQUIRED_RUNTIME_MEMBERS = [
    "./.build-identity.json",
    "./requirements-langgraph-runtime.txt",
    "./templates/admin-vue-dist/index.html",
    "./packages/xcagi_langgraph_core/langgraph/graph/state.py",
    "./packages/xcagi_langgraph_checkpoint/langgraph/checkpoint/base/__init__.py",
    "./packages/xcagi_langgraph_checkpoint_backends/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py",
    "./packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py",
    "./packages/xcagi_langgraph_prebuilt/langgraph/prebuilt/tool_node.py",
    "./packages/xcagi_langgraph_sdk/langgraph_sdk/client.py",
]


def _write_archive(path: Path, names: list[str]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name in names:
            payload = name.encode()
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def _verify(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VERIFIER), "--archive", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_archive_accepts_clean_members(tmp_path: Path) -> None:
    archive = tmp_path / "clean.tar.gz"
    _write_archive(archive, ["./app/main.py", *REQUIRED_RUNTIME_MEMBERS])

    result = _verify(archive)

    assert result.returncode == 0, result.stderr
    assert '"status": "verified"' in result.stdout


def test_release_archive_rejects_missing_vendored_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "missing-runtime.tar.gz"
    _write_archive(archive, ["./app/main.py", "./templates/admin-vue-dist/index.html"])

    result = _verify(archive)

    assert result.returncode != 0
    assert "missing required runtime members" in result.stderr
    assert "xcagi_langgraph_core" in result.stderr


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["./app/main.py", "./app/main.py"], "duplicate member"),
        (["./app/._main.py"], "AppleDouble metadata"),
        (["./.env.production"], "environment files"),
        (["./app/__pycache__/main.pyc"], "forbidden path component"),
        (["../outside.txt"], "unsafe member path"),
    ],
)
def test_release_archive_rejects_unsafe_members(
    tmp_path: Path,
    names: list[str],
    message: str,
) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _write_archive(archive, names)

    result = _verify(archive)

    assert result.returncode == 1
    assert message in result.stderr


def test_pack_release_invokes_archive_verifier() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")

    assert "export COPYFILE_DISABLE=1" in script
    assert 'python3 "$ARCHIVE_VERIFY" --archive "$TARBALL"' in script
    assert '"$SCRIPT_DIR/lib/verify_release_archive.py"' in script


def test_pack_release_bundles_immutable_dr_sync_helper() -> None:
    pack = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")
    auto_update = (FHD_ROOT / "scripts/deploy/fhd-auto-update.sh").read_text(encoding="utf-8")

    assert 'DR_RELEASE_SYNC="$REPO_ROOT/ops/dr/xcmax_release_sync.sh"' in pack
    assert 'cp "$DR_RELEASE_SYNC" "$STAGING/scripts/deploy/xcmax-release-sync.sh"' in pack
    assert 'bundled_sync="$DEPLOY_ROOT/scripts/deploy/xcmax-release-sync.sh"' in auto_update
