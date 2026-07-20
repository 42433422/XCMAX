from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


def test_immutable_release_is_exact_sha_atomic_and_rolls_back() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text(encoding="utf-8")

    assert "XCMAX_TARGET_SHA must be a full 40-character commit SHA" in script
    assert 'git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA"' in script
    assert "releases/${TARGET_SHA}" in script
    assert 'mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"' in script
    assert "exact-SHA local health verification failed" in script
    assert 'sha256sum "$SOURCE_ARCHIVE"' in script
    assert 'payload.get("artifact_sha256") == expected_artifact' in script
    assert (
        'verify_health_identity "$PUBLIC_HEALTH_URL" "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA"'
        in script
    )
    assert "rollback" in script
    assert "reset --hard" not in script
    assert "/etc/xcmax" in script


def test_production_workflow_deploys_only_successful_tested_main_sha() -> None:
    source = yaml.safe_load((ROOT / ".github/workflows/prod-deploy.yml").read_text())
    published = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/modstore-prod-deploy.yml").read_text()
    )

    for workflow in (source, published):
        trigger = workflow[True]
        assert trigger["workflow_run"]["workflows"] == ["CI - Backend Python"]
        deploy = workflow["jobs"]["deploy"]
        assert "workflow_run.conclusion == 'success'" in deploy["if"]
        rendered = str(deploy)
        assert "TARGET_SHA" in rendered
        assert "xcmax-immutable-release.sh" in rendered
        assert "reset --hard" not in rendered
