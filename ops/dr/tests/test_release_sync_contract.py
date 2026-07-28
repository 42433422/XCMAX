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
