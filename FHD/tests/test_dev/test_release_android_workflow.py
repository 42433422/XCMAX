from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

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
    assert "versionCode='${EXPECTED_VERSION_CODE}'" in workflow


def test_android_candidate_version_comes_from_the_selected_source_catalog(tmp_path: Path) -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["workflow_dispatch"]["inputs"]["version"]["type"] == "string"
    steps = workflow["jobs"]["assemble-release"]["steps"]
    resolve_version = next(step["run"] for step in steps if step.get("id") == "release_version")
    release = json.loads((FHD_ROOT / "config" / "download_release.json").read_text())[
        "version_lock"
    ]
    output = tmp_path / "github-output"
    cwd = FHD_ROOT / "mobile-flutter-poc"
    env = {**os.environ, "GITHUB_OUTPUT": str(output), "RELEASE_VERSION": release}
    subprocess.run(["bash", "-c", resolve_version], cwd=cwd, env=env, check=True)
    assert output.read_text().splitlines() == [
        f"version={release}",
        f"toolchain_version={release.rsplit('.', 1)[0]}",
    ]
    env["RELEASE_VERSION"] = "0.0.0.0"
    result = subprocess.run(["bash", "-c", resolve_version], cwd=cwd, env=env, capture_output=True)
    assert result.returncode != 0


def test_flutter_android_package_staging_has_no_legacy_native_inputs() -> None:
    workflow = WORKFLOW.read_text()
    stage_script = STAGE_SCRIPT.read_text()

    assert 'bash FHD/scripts/mobile/stage-release-packages.sh "${args[@]}"' in workflow
    assert "mobile-flutter-poc/build/app/outputs/flutter-apk/app-release.apk" in workflow
    assert "mobile-flutter-poc/build/app/outputs/flutter-apk/app-release.apk" in stage_script
    assert "mobile-android" not in stage_script
    assert "harmony" not in stage_script.lower()
