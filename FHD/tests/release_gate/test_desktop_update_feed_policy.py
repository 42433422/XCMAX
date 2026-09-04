"""Desktop updater and security-gate release policy checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_macos_update_feed_is_generated_from_zip(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for desktop updater policy test")

    generator = REPO_ROOT / "scripts" / "package" / "generate-update-metadata.mjs"
    update_zip = tmp_path / "XCAGI-Enterprise-1.0.0.0-mac-arm64.zip"
    update_zip.write_bytes(b"signed-app-archive-fixture")
    env = {
        **os.environ,
        "XCAGI_BUILD_SHA": "a" * 40,
        "XCAGI_PRODUCT_VERSION": "1.0.0.0",
        "XCAGI_RELEASE_MEDIA_JSON": (
            '[{"posterUrl":"https://cdn.example.com/a.webp",'
            '"videoUrl":"https://cdn.example.com/a.mp4","caption":"demo"}]'
        ),
    }

    subprocess.run(
        [node, str(generator), str(update_zip), "1.0.0", "mac"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    feed = (tmp_path / "latest-mac.yml").read_text(encoding="utf-8")
    assert f"url: {update_zip.name}" in feed
    assert f"path: {update_zip.name}" in feed
    assert "buildSha: " + "a" * 40 in feed
    assert "releaseId: xcagi-1.0.0.0-" + "a" * 40 in feed
    assert "releaseDate:" in feed
    assert "releaseMedia:" in feed
    assert "https://cdn.example.com/a.webp" in feed
    assert "https://cdn.example.com/a.mp4" in feed


def test_update_feed_can_point_to_immutable_sha_directory(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for desktop updater policy test")

    generator = REPO_ROOT / "scripts" / "package" / "generate-update-metadata.mjs"
    update_zip = tmp_path / "XCAGI-Enterprise-1.0.0.1-mac-arm64.zip"
    update_zip.write_bytes(b"immutable-signed-app")
    git_sha = "b" * 40
    prefix = f"https://xiu-ci.com/releases/builds/1.0.0.1/{git_sha}/enterprise"
    env = {
        **os.environ,
        "XCAGI_BUILD_SHA": git_sha,
        "XCAGI_PRODUCT_VERSION": "1.0.0.1",
        "XCAGI_ARTIFACT_URL_PREFIX": prefix,
    }

    subprocess.run(
        [node, str(generator), str(update_zip), "1.0.0", "mac"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    feed = (tmp_path / "latest-mac.yml").read_text(encoding="utf-8")
    expected = f"{prefix}/{update_zip.name}"
    assert f"url: {expected}" in feed
    assert f"path: {expected}" in feed
    assert f"releaseId: xcagi-1.0.0.1-{git_sha}" in feed


def test_macos_update_feed_rejects_dmg(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for desktop updater policy test")

    generator = REPO_ROOT / "scripts" / "package" / "generate-update-metadata.mjs"
    dmg = tmp_path / "XCAGI-Enterprise-1.0.0.0-mac-arm64.dmg"
    dmg.write_bytes(b"dmg-fixture")
    result = subprocess.run(
        [node, str(generator), str(dmg), "1.0.0", "mac"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "requires a ZIP artifact" in result.stderr
    assert not (tmp_path / "latest-mac.yml").exists()


def test_release_pipeline_uploads_mac_zip_and_never_synthesizes_scan_success() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    uploader = (REPO_ROOT / "scripts" / "deploy" / "upload-desktop-skus.sh").read_text(
        encoding="utf-8"
    )
    scanner = (REPO_ROOT / "desktop" / "scripts" / "security-scan.sh").read_text(
        encoding="utf-8"
    )
    finalize = (REPO_ROOT / "scripts" / "package" / "finalize-macos-dmg.sh").read_text(
        encoding="utf-8"
    )

    assert workflow.count("--include='*.zip'") == 1
    assert workflow.count("--include='*.zip.blockmap'") == 1
    assert "publish_payload()" in workflow
    assert workflow.count('publish_payload "') == 2
    assert (
        'immutable_root="/var/www/update/releases/builds/${version}/${release_sha}"'
        in workflow
    )
    assert workflow.count("publish_stable_metadata_atomically") == 3
    assert "verify-public-windows-signature:" in workflow
    assert workflow.index("verify-public-windows-signature:") < workflow.index(
        "publish-website-pointer:"
    )
    verify_download_job = workflow.split("  verify-download:", 1)[1].split(
        "\n  verify-public-windows-signature:", 1
    )[0]
    assert "Publish verified website download pointer" not in verify_download_job
    pointer_job = workflow.split("  publish-website-pointer:", 1)[1].split(
        "\n  github-release:", 1
    )[0]
    assert "Publish verified website download pointer" in pointer_job
    assert "needs.verify-public-windows-signature.result == 'success'" in pointer_job
    assert "--delay-updates" in workflow
    assert "-o -name '*.zip'" in workflow
    assert '"XCAGI-*-${VERSION}-mac-*.zip"' in uploader
    assert '"XCAGI-*-${VERSION}-mac-*.zip.blockmap"' in uploader
    assert "/var/www/update/releases/stable" in uploader
    assert "Node.js 22.12+ is required" in scanner
    assert "synthetic green report" in scanner
    assert 'electronegativity.csv" -r -v false || true' not in scanner
    assert 'electronegativity.sarif" -r -v false || true' not in scanner
    # DMG notarize must not overwrite ZIP-based latest-mac.yml
    assert "node scripts/package/generate-update-metadata.mjs" not in finalize
    assert "ZIP update feed left untouched" in finalize


def test_emergency_mac_feed_repair_preserves_release_identity_and_path_parity() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "fix-mac-update-feed.yml"
    ).read_text(encoding="utf-8")
    restorer = (
        REPO_ROOT / "scripts" / "deploy" / "restore_mac_feed_from_artifact.sh"
    ).read_text(encoding="utf-8")

    assert "actions: read" in workflow
    assert "contents: write" in workflow
    assert "source_run_id" in workflow
    assert "security_scan_run_id:" in workflow
    assert "previous_security_scan_run_id:" in workflow
    assert "ref: ${{ inputs.build_sha }}" in workflow
    assert "verify_security_scan_pair.py" in workflow
    assert '--release-sha "${{ inputs.build_sha }}"' in workflow
    assert "--name xcagi-desktop-macos-enterprise" in workflow
    assert "RUN_CONCLUSION" in workflow
    assert "RUN_WORKFLOW" in workflow
    assert "SOURCE_RUN_SHA" in workflow
    assert "SOURCE_ARTIFACT_ID" in workflow
    assert "SOURCE_ARTIFACT_SIZE" in workflow
    assert (
        'ZIP_BUILD_SHA="$(python3 scripts/deploy/extract_zip_build_sha.py' in workflow
    )
    assert "Canonical ZIP identity differs from the source release run" in workflow
    assert "build_sha differs from the canonical ZIP identity" in workflow
    assert '"https://xiu-ci.com/xcagi-v${PRODUCT_VERSION}/manifest.json"' in workflow
    assert 'MANIFEST_SHA="$(printf' in workflow
    assert (
        "Canonical ZIP identity does not match the published release manifest"
        in workflow
    )
    assert 'STABLE_DEST="/var/www/update/releases/stable/enterprise"' in workflow
    assert 'OFFICIAL_DEST="/var/www/xcagi-v${PRODUCT_VERSION}/enterprise"' in workflow
    assert 'RELEASE_TAG="xcagi-v${PRODUCT_VERSION}"' in workflow
    assert 'gh release upload "${RELEASE_TAG}"' in workflow
    assert 'RELEASE_ASSETS="$(gh release view' in workflow
    assert "GitHub release asset size mismatch" in workflow
    assert "/actions/artifacts/${SOURCE_ARTIFACT_ID}/zip" in workflow
    assert "ARTIFACT_URL_B64" in workflow
    assert "EXPECTED_ARTIFACT_SIZE" in workflow
    assert "restore_mac_feed_from_artifact.sh" in workflow
    assert 'scp "${SSH_OPTS[@]}" "${ZIP_PATH}"' not in workflow
    assert 'download_parts="${DOWNLOAD_PARTS:-16}"' in restorer
    assert '--range "${range_start}-${range_end}"' in restorer
    assert "stat -c '%s' \"${part_paths[part_index]}\"" in restorer
    assert "--retry-all-errors" not in restorer
    assert 'unzip -q "${artifact_path}"' in restorer
    assert 'actual_build_sha="$(' in restorer
    assert (
        'cp -f "${OFFICIAL_DEST}/${ZIP_NAME}.part" "${STABLE_DEST}/${ZIP_NAME}.part"'
        in restorer
    )
    assert (
        'cmp -s "${OFFICIAL_DEST}/latest-mac.yml" "${STABLE_DEST}/latest-mac.yml"'
        in restorer
    )
    assert restorer.index('mv -f "${OFFICIAL_DEST}/${ZIP_NAME}.part"') < restorer.index(
        'mv -f "${OFFICIAL_DEST}/latest-mac.yml.part"'
    )


def test_unverifiable_local_mac_feed_lane_is_fail_closed() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "publish-local-mac-feed.yml"
    ).read_text(encoding="utf-8")

    assert "local upload (disabled)" in workflow
    assert "Use Release Orchestrator" in workflow
    assert "exit 1" in workflow
    assert "scp " not in workflow
    assert "ssh " not in workflow
    assert "latest-mac.yml" not in workflow


def test_update_metadata_requires_full_build_sha(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for desktop updater policy test")

    generator = REPO_ROOT / "scripts" / "package" / "generate-update-metadata.mjs"
    update_zip = tmp_path / "XCAGI-Enterprise-1.0.0.0-mac-arm64.zip"
    update_zip.write_bytes(b"signed-app-archive-fixture")
    env = {**os.environ}
    env.pop("XCAGI_BUILD_SHA", None)
    env.pop("GITHUB_SHA", None)
    # Force empty SHA via bogus cwd without git? Keep generator fail by setting invalid SHA.
    env["XCAGI_BUILD_SHA"] = "not-a-sha"
    result = subprocess.run(
        [node, str(generator), str(update_zip), "1.0.0", "mac"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "buildSha" in result.stderr
    assert not (tmp_path / "latest-mac.yml").exists()


def test_desktop_updater_rejects_same_version_downgrade_by_release_date() -> None:
    updater = (REPO_ROOT / "desktop" / "updater.ts").read_text(encoding="utf-8")
    assert "isSameVersionRebuildNewer" in updater
    assert "allowDowngrade = false" in updater
    assert "remoteReleaseDate" in updater
    assert "readLocalBuildTimeMs" in updater
    assert (
        "return Boolean(remoteSha && localSha && remoteSha !== localSha)" not in updater
    )
