from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> str:
    return (FHD_ROOT / ".github" / "workflows" / "windows-macalign-hotfix.yml").read_text(
        encoding="utf-8"
    )


def test_unsigned_windows_lane_is_quarantined_and_has_no_publish_job() -> None:
    workflow = _workflow()

    assert "windows:\n    runs-on: windows-latest" in workflow
    assert "Public delivery: forbidden" in workflow
    assert "WINDOWS-QUARANTINE.json" in workflow
    assert "publish:" not in workflow
    assert "Publish mac-align hotfix to CVM" not in workflow
    assert "SERVER_SSH_KEY" not in workflow
    assert "/var/www/" not in workflow


def test_unsigned_windows_lane_requires_exact_sha_two_day_security_evidence() -> None:
    workflow = _workflow()

    assert "release_sha:" in workflow
    assert "security_scan_run_id:" in workflow
    assert "previous_security_scan_run_id:" in workflow
    assert "ref: ${{ inputs.release_sha }}" in workflow
    assert "verify_security_scan_pair.py" in workflow
    assert '--release-sha "${{ inputs.release_sha }}"' in workflow


def test_unsigned_windows_artifact_cannot_be_mistaken_for_an_update_feed() -> None:
    workflow = _workflow()

    assert "xcagi-windows-unsigned-quarantine-${{ inputs.release_sha }}" in workflow
    assert "latest.yml" not in workflow
    assert "download-windows-hotfix.json" not in workflow
    assert "xiu-ci.com" not in workflow
