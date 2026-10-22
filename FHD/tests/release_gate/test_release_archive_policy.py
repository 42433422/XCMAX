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
    "./scripts/deploy/xcmax-release-sync.sh",
    "./scripts/deploy/xcmax_release_sync_prune.py",
    "./scripts/deploy/lib/mod_tree_guard.py",
    "./scripts/deploy/lib/verify_release_archive.py",
    "./scripts/deploy/lib/service_quiescence.sh",
    "./scripts/deploy/lib/apply_recovery.sh",
    "./scripts/deploy/lib/version.sh",
    "./scripts/deploy/fhd-load-release-image.sh",
    "./scripts/autonomy/corp_site_health_probe.py",
    "./scripts/autonomy/cvm_autonomy_watcher.py",
    "./scripts/ci/_approval_ledger_client.py",
    "./scripts/ci/_im_notify_client.py",
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


def _write_member_archive(path: Path, members: list[tarfile.TarInfo]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for member in members:
            payload = member.name.encode()
            if member.isfile():
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            else:
                archive.addfile(member)


def test_release_archive_rejects_parent_component_alias_even_when_it_stays_in_root(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "path-alias.tar.gz"
    _write_archive(archive, ["./app/file.py", "./app/../app/file.py", *REQUIRED_RUNTIME_MEMBERS])

    result = _verify(archive)

    assert result.returncode == 1
    assert "unsafe member path" in result.stderr


def test_release_archive_rejects_duplicate_normalized_targets(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate-target.tar.gz"
    _write_archive(archive, ["./app/file.py", "app/file.py", *REQUIRED_RUNTIME_MEMBERS])

    result = _verify(archive)

    assert result.returncode == 1
    assert "duplicate member target: app/file.py" in result.stderr


def test_release_archive_rejects_member_through_symlink_parent(tmp_path: Path) -> None:
    archive = tmp_path / "symlink-parent.tar.gz"
    symlink = tarfile.TarInfo("./link")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "safe-dir"
    members = [symlink, *[tarfile.TarInfo(name) for name in ("./link/overwrite.py",)]]
    members[-1].size = len(members[-1].name.encode())
    members = [*members, *[tarfile.TarInfo(name) for name in REQUIRED_RUNTIME_MEMBERS]]
    for member in members:
        if member.isfile():
            member.size = len(member.name.encode())
    _write_member_archive(archive, members)

    result = _verify(archive)

    assert result.returncode == 1
    assert "member traverses symlink parent" in result.stderr


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_release_payload_rejects_links_even_to_an_internal_file(tmp_path: Path, kind) -> None:
    archive = tmp_path / "internal-link.tar.gz"
    link = tarfile.TarInfo("./linked")
    link.type, link.linkname = kind, "app/file.py"
    _write_member_archive(archive, [link, *map(tarfile.TarInfo, REQUIRED_RUNTIME_MEMBERS)])
    result = _verify(archive)
    assert result.returncode == 1
    assert "links are forbidden" in result.stderr


@pytest.mark.parametrize("name,kind", [("/", tarfile.DIRTYPE), (".", tarfile.SYMTYPE)])
def test_root_member_cannot_bypass_absolute_path_or_link_checks(tmp_path: Path, name, kind) -> None:
    archive = tmp_path / "root-member.tar.gz"
    root = tarfile.TarInfo(name)
    root.type, root.linkname = kind, "/outside"
    _write_member_archive(archive, [root, *map(tarfile.TarInfo, REQUIRED_RUNTIME_MEMBERS)])
    assert _verify(archive).returncode == 1


def test_every_deployment_tar_extractor_verifies_before_unpacking() -> None:
    apply = (FHD_ROOT / "scripts/deploy/fhd-apply-release.sh").read_text(encoding="utf-8")
    push = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")
    staging = (FHD_ROOT / "scripts/deploy/fhd-bootstrap-staging-cvm.sh").read_text(encoding="utf-8")
    workflow = (FHD_ROOT.parent / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")
    root_ci = (FHD_ROOT.parent / ".github/workflows/fhd-ci-cd.yml").read_text(encoding="utf-8")
    fhd_ci = (FHD_ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8")

    assert apply.index('python3 "$ARCHIVE_VERIFY" --archive "$TARBALL"') < apply.index(
        'tar -xzf "$TARBALL"'
    )
    assert push.index('python3 "$VERIFY" --archive %q') < push.index('tar -xzf %q -C "$BOOTSTRAP"')
    assert staging.index('python3 "$TRUSTED_ARCHIVE_VERIFY" --archive "$TARBALL"') < staging.index(
        'tar -xzf "$TARBALL"'
    )
    assert workflow.index(r'python3 "\$TRUSTED_VERIFIER" --archive "\$TARBALL"') < workflow.index(
        r'tar -xzf "\$TARBALL"'
    )
    for ci_workflow in (root_ci, fhd_ci):
        assert ci_workflow.index(
            'python3 scripts/deploy/lib/verify_release_archive.py --archive "$artifact"'
        ) < ci_workflow.index('tar -xzf "$artifact"')
    assert "verifier_source = base64.b64decode(verifier_b64, validate=True)" in push
    assert 'f"{sha}:FHD/scripts/deploy/lib/verify_release_archive.py"' in (
        FHD_ROOT / "scripts/deploy/fhd-pack-release.sh"
    ).read_text(encoding="utf-8")


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
        (["./mods/.install-receipts/customer/receipt.json"], "forbidden path component"),
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
    assert '"archive_verifier_sha256": archive_verify_sha256' in script


def test_pack_release_bundles_immutable_dr_sync_helper() -> None:
    pack = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")
    auto_update = (FHD_ROOT / "scripts/deploy/fhd-auto-update.sh").read_text(encoding="utf-8")

    assert 'DR_RELEASE_SYNC="$REPO_ROOT/ops/dr/xcmax_release_sync.sh"' in pack
    assert 'DR_RELEASE_SYNC_PRUNE="$REPO_ROOT/ops/dr/xcmax_release_sync_prune.py"' in pack
    assert 'cp "$DR_RELEASE_SYNC" "$STAGING/scripts/deploy/xcmax-release-sync.sh"' in pack
    assert (
        'cp "$DR_RELEASE_SYNC_PRUNE" "$STAGING/scripts/deploy/xcmax_release_sync_prune.py"' in pack
    )
    assert 'bundled_sync="$DEPLOY_ROOT/scripts/deploy/xcmax-release-sync.sh"' in auto_update


def test_pack_release_bundles_exact_autonomy_runtime() -> None:
    pack = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")
    apply_release = (FHD_ROOT / "scripts/deploy/fhd-apply-release.sh").read_text(encoding="utf-8")

    assert '"$FHD_ROOT/scripts/autonomy/" "$STAGING/scripts/autonomy/"' in pack
    assert '"$FHD_ROOT/scripts/ci/_approval_ledger_client.py"' in pack
    assert '"$FHD_ROOT/scripts/ci/_im_notify_client.py"' in pack
    assert '"$TMP/scripts/autonomy/" "$DEPLOY_ROOT/scripts/autonomy/"' in apply_release
    assert '"$TMP/scripts/ci/" "$DEPLOY_ROOT/scripts/ci/"' in apply_release
    assert '"$BACKUP/scripts/autonomy/" "$DEPLOY_ROOT/scripts/autonomy/"' in apply_release
    assert '"$BACKUP/scripts/ci/" "$DEPLOY_ROOT/scripts/ci/"' in apply_release


def test_cvm_watcher_sets_pythonpath_for_release_and_fallback_probes() -> None:
    watcher = (FHD_ROOT / ".github/workflows/cvm-autonomy-watcher.yml").read_text(encoding="utf-8")

    assert 'PROBE_ROOT="${PROBE_DEPLOY_ROOT}"' in watcher
    assert 'PROBE_ROOT="/opt/xcmax/current/FHD"' in watcher
    assert 'PYTHONPATH="\\$PROBE_ROOT\\${PYTHONPATH:+:\\$PYTHONPATH}"' in watcher
    assert 'WATCHER_ROOT="${DEPLOY_ROOT}"' in watcher
    assert 'WATCHER_ROOT="/opt/xcmax/current/FHD"' in watcher
    assert 'PYTHONPATH="\\$WATCHER_ROOT\\${PYTHONPATH:+:\\$PYTHONPATH}"' in watcher
