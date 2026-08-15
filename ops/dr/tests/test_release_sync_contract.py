from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


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
    bounded_clear = text.index("rsync -a --delete --force", selector)
    verified_clear = text.index("DR 入站候选腾位后仍包含文件", bounded_clear)
    upload = text.index("rsync -a --partial --delay-updates", verified_clear)

    assert lock < selector < bounded_clear < verified_clear < upload
    assert '[[ "$victim" =~ ^[0-9a-f]{40}$ && "$victim" != "$SHA" ]]' in text
    assert "OPS_DR_INCOMING_COMPONENT_KEEP" in text
    assert '"$empty_source/"' in text
    assert '"${TARGET}:${REMOTE_ROOT}/runtime-releases/${victim}/"' in text
    assert "index($5, prefix) == 1" in text


def test_empty_tree_sync_really_clears_release_contents() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        empty = root / "empty"
        victim = root / ("a" * 40)
        empty.mkdir()
        (victim / "nested").mkdir(parents=True)
        (victim / "release.SHA").write_text("a" * 40, encoding="utf-8")
        (victim / "nested" / "payload").write_bytes(b"payload")

        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--force",
                f"{empty}/",
                f"{victim}/",
            ],
            check=True,
        )

        assert list(victim.iterdir()) == []
