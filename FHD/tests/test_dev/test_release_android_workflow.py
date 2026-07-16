from __future__ import annotations

from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = FHD_ROOT / ".github" / "workflows" / "release-android.yml"
STAGE_SCRIPT = FHD_ROOT / "scripts" / "mobile" / "stage-release-packages.sh"


def test_android_release_requires_real_signing_and_verifies_the_apk() -> None:
    workflow = WORKFLOW.read_text()

    assert "Configure release signing (required)" in workflow
    assert "Configure release signing (optional)" not in workflow
    for secret in (
        "ANDROID_KEYSTORE_BASE64",
        "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS",
        "ANDROID_KEY_PASSWORD",
    ):
        assert f"secrets.{secret}" in workflow
        assert secret in workflow

    assert "${required} is required for a stable Android release" in workflow
    assert 'XCAGI_REQUIRE_RELEASE_SIGNING: "1"' in workflow
    assert "apksigner" in workflow
    assert "Android Debug" in workflow
    assert "com.xiuci.xcagi.mobile.enterprise" in workflow
    assert "versionName='${EXPECTED_VERSION}'" in workflow


def test_android_only_mode_is_the_release_default_after_harmony_archival() -> None:
    workflow = WORKFLOW.read_text()
    stage_script = STAGE_SCRIPT.read_text()

    assert "android_only:" in workflow
    assert "default: true" in workflow
    assert 'if [[ "${{ inputs.android_only }}" != "false" ]]' in workflow
    assert "args+=(--android-only)" in workflow
    assert 'bash FHD/scripts/mobile/stage-release-packages.sh "${args[@]}"' in workflow

    assert "ANDROID_ONLY=1" in stage_script
    assert "--android-only)" in stage_script
    assert 'if [[ "${ANDROID_ONLY}" -eq 1 ]]' in stage_script
    assert "Product shipping is Android-only" in stage_script
    assert 'MODULE_ROOT="${REPO_ROOT}/archive/mobile/mobile-harmony"' in stage_script
