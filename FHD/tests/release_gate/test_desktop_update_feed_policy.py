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
    assert "releaseMedia:" in feed
    assert "https://cdn.example.com/a.webp" in feed
    assert "https://cdn.example.com/a.mp4" in feed


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
    scanner = (REPO_ROOT / "desktop" / "scripts" / "security-scan.sh").read_text(encoding="utf-8")
    finalize = (REPO_ROOT / "scripts" / "package" / "finalize-macos-dmg.sh").read_text(
        encoding="utf-8"
    )

    assert workflow.count("--include='*.zip'") >= 3
    assert workflow.count("--include='*.zip.blockmap'") >= 3
    assert '"$src_dir"/*.zip' in workflow
    assert '"XCAGI-*-${VERSION}-mac-*.zip"' in uploader
    assert '"XCAGI-*-${VERSION}-mac-*.zip.blockmap"' in uploader
    assert "/var/www/update/releases/stable" in uploader
    assert "Node.js 20+ is required" in scanner
    assert "synthetic green report" in scanner
    assert 'electronegativity.csv" -r -v false || true' not in scanner
    assert 'electronegativity.sarif" -r -v false || true' not in scanner
    # DMG notarize must not overwrite ZIP-based latest-mac.yml
    assert "node scripts/package/generate-update-metadata.mjs" not in finalize
    assert "ZIP update feed left untouched" in finalize


def test_emergency_mac_feed_repair_preserves_release_identity_and_path_parity() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "fix-mac-update-feed.yml").read_text(
        encoding="utf-8"
    )

    assert "actions: read" in workflow
    assert "source_run_id" in workflow
    assert "--name xcagi-desktop-macos-enterprise" in workflow
    assert "RUN_CONCLUSION" in workflow
    assert "RUN_WORKFLOW" in workflow
    assert "SOURCE_RUN_SHA" in workflow
    assert 'ZIP_BUILD_SHA="$(python3 scripts/deploy/extract_zip_build_sha.py' in workflow
    assert "Canonical ZIP identity differs from the source release run" in workflow
    assert "build_sha override differs from the canonical ZIP identity" in workflow
    assert '"https://xiu-ci.com/xcagi-v${PRODUCT_VERSION}/manifest.json"' in workflow
    assert 'MANIFEST_SHA="$(printf' in workflow
    assert "Canonical ZIP identity does not match the published release manifest" in workflow
    assert 'STABLE_DEST="/var/www/update/releases/stable/enterprise"' in workflow
    assert 'OFFICIAL_DEST="/var/www/xcagi-v${PRODUCT_VERSION}/enterprise"' in workflow
    assert '"root@${HOST}:${OFFICIAL_DEST}/${ZIP_NAME}.part"' in workflow
    assert '"root@${HOST}:${OFFICIAL_DEST}/latest-mac.yml.part"' in workflow
    assert "cp -f '${OFFICIAL_DEST}/${ZIP_NAME}.part' '${STABLE_DEST}/${ZIP_NAME}.part'" in workflow
    assert "cmp -s '${OFFICIAL_DEST}/latest-mac.yml' '${STABLE_DEST}/latest-mac.yml'" in workflow
    assert workflow.index("mv -f '${OFFICIAL_DEST}/${ZIP_NAME}.part'") < workflow.index(
        "mv -f '${OFFICIAL_DEST}/latest-mac.yml.part'"
    )
