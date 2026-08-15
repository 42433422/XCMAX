from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "xcmax_release_sync.sh"


def test_fhd_release_sync_does_not_require_a_git_object() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    component_branch = text.index('if [[ "$COMPONENT" == "modstore" ]]')
    git_object_check = text.index('git -C "$SOURCE_ROOT" cat-file -e "${SHA}^{commit}"')
    fhd_branch = text.index("\nelse\n", component_branch)

    assert component_branch < git_object_check < fhd_branch
    assert '[[ "${manifest_values[0]:-}" == "$SHA" ]]' in text[fhd_branch:]


def test_release_sync_prunes_only_validated_component_candidates() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lock = text.index('flock -w "$TRANSFER_WAIT_SECONDS" 8')
    selector = text.index('python3 "$PRUNE_HELPER"', lock)
    bounded_clear = text.index(
        "rsync -r --force --delete-missing-args --ignore-missing-args", selector
    )
    verified_clear = text.index("DR 入站候选腾位后仍存在", bounded_clear)
    upload = text.index("rsync -a --partial --delay-updates", verified_clear)

    assert lock < selector < bounded_clear < verified_clear < upload
    assert '[[ "$victim" =~ ^[0-9a-f]{40}$ && "$victim" != "$SHA" ]]' in text
    assert "OPS_DR_INCOMING_COMPONENT_KEEP" in text
    assert '"$missing_source_dir/$victim"' in text
    assert '"${TARGET}:${REMOTE_ROOT}/runtime-releases/"' in text
    assert "$5 == victim" in text
    assert "index($5, prefix) == 1" in text


def test_missing_source_sync_really_removes_release_directory() -> None:
    rsync_help = subprocess.run(
        ["rsync", "--help"], capture_output=True, check=True, text=True
    )
    if "--delete-missing-args" not in rsync_help.stdout:
        pytest.skip("system rsync does not support --delete-missing-args")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        missing_source_dir = root / "missing"
        destination = root / "destination"
        missing_source_dir.mkdir()
        victim = destination / ("a" * 40)
        (victim / "nested").mkdir(parents=True)
        (victim / "release.SHA").write_text("a" * 40, encoding="utf-8")
        (victim / "nested" / "payload").write_bytes(b"payload")

        subprocess.run(
            [
                "rsync",
                "-r",
                "--force",
                "--delete-missing-args",
                "--ignore-missing-args",
                str(missing_source_dir / victim.name),
                f"{destination}/",
            ],
            check=True,
        )

        assert not victim.exists()
