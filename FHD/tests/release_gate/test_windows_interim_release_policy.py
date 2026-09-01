from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> str:
    return (FHD_ROOT / ".github" / "workflows" / "windows-macalign-hotfix.yml").read_text(
        encoding="utf-8"
    )


def test_windows_interim_build_and_publish_are_split_across_native_runners() -> None:
    workflow = _workflow()

    assert "windows:\n    runs-on: windows-latest" in workflow
    assert "publish:\n    if:" in workflow
    assert "needs: windows" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "uses: actions/download-artifact@v4" in workflow
    assert "name: xcagi-windows-macalign-hotfix" in workflow


def test_windows_interim_upload_is_resumable_and_never_clears_partial_first() -> None:
    workflow = _workflow()

    assert "timeout-minutes: 300" in workflow
    assert 'remote_stage="/var/tmp/xcagi-macalign-${GITHUB_SHA}"' in workflow
    assert "rsync --archive --partial --append-verify --timeout=180" in workflow
    assert 'while [ "$attempt" -le 24 ]' in workflow
    assert "partial retained for resume" in workflow
    assert "rm -rf '$remote_stage' && mkdir" not in workflow


def test_windows_interim_publish_remains_checksum_gated_and_atomic() -> None:
    workflow = _workflow()

    assert 'actual="$(sha256sum "$stage/$artifact"' in workflow
    assert 'test "$actual" = "$expected"' in workflow
    assert 'payload["git_sha"] == git_sha' in workflow
    assert 'mv -f "$destination/$artifact$suffix" "$destination/$artifact"' in workflow
    assert "Verify public interim installer, download center, and changelog" in workflow
    assert 'test "$(sha256sum "$tmpdir/installer.exe"' in workflow
