from __future__ import annotations

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
    bounded_delete = text.index("--delete-missing-args", selector)
    upload = text.index("rsync -a --partial --delay-updates", bounded_delete)

    assert lock < selector < bounded_delete < upload
    assert '[[ "$victim" =~ ^[0-9a-f]{40}$ && "$victim" != "$SHA" ]]' in text
    assert "OPS_DR_INCOMING_COMPONENT_KEEP" in text
    assert '"${TARGET}:${REMOTE_ROOT}/runtime-releases/${victim}"' in text
