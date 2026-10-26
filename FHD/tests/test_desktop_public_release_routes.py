from __future__ import annotations

import json
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_versioned_public_download_routes_are_not_pinned_to_a_retired_release() -> None:
    snippet = (
        REPO_ROOT
        / "成都修茈科技有限公司"
        / "deploy"
        / "nginx"
        / "snippets"
        / "xcagi-cos-alias.inc.conf"
    ).read_text(encoding="utf-8")

    assert "location ~ ^/xcagi-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/" in snippet
    assert "{3}" not in snippet
    assert "root /var/www;" in snippet
    assert "try_files $uri =404;" in snippet
    assert "alias /root/成都修茈科技有限公司/download-release.json;" in snippet
    assert (
        "alias /var/www/update/releases/stable/enterprise/download-windows-hotfix.json;" in snippet
    )
    assert "alias /root/成都修茈科技有限公司/download-windows-hotfix.json;" not in snippet


def test_standalone_vhost_uses_the_same_versioned_public_download_contract() -> None:
    config = (REPO_ROOT / "成都修茈科技有限公司" / "nginx-xiu-ci-root.conf").read_text(
        encoding="utf-8"
    )

    assert "location ~ ^/xcagi-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/" in config
    assert "{3}" not in config
    assert "alias /root/成都修茈科技有限公司/download-release.json;" in config
    assert (
        "alias /var/www/update/releases/stable/enterprise/download-windows-hotfix.json;" in config
    )
    assert "alias /root/成都修茈科技有限公司/download-windows-hotfix.json;" not in config


def test_corporate_deploy_syncs_the_versioned_download_snippet_before_nginx_reload() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "corp-site-deploy.yml").read_text(
        encoding="utf-8"
    )
    sync_script = (
        REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "scripts" / "sync-nginx-xiu-ci-snippets.sh"
    ).read_text(encoding="utf-8")

    assert 'bash "${SITE_ROOT}/deploy/scripts/sync-nginx-xiu-ci-snippets.sh"' in workflow
    assert 'git -C "${REMOTE_ROOT}" reset --hard "origin/${BRANCH}"' in workflow
    assert "exact server worktree sha=${DEPLOY_SHA}" in workflow
    assert "xcagi-cos-alias.inc.conf" in sync_script
    assert "merge-nginx-xiu-ci-snippets.py" in sync_script


def test_site_refreshes_preserve_a_verified_desktop_release_pointer() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "corp-site-deploy.yml").read_text(
        encoding="utf-8"
    )
    auto_update = (
        REPO_ROOT
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "scripts"
        / "xcmax-site-auto-update.sh"
    ).read_text(encoding="utf-8")

    assert 'cp -f "${GIT_SITE}/download-release.json"' not in workflow
    assert "preserving release-managed download-release.json" in workflow
    assert "preserving release-managed download-windows-hotfix.json" in workflow
    assert "seed_src=" not in auto_update
    assert "保留发布流程管理的 download-release.json" in auto_update
    assert "保留发布流程管理的 download-windows-hotfix.json" in auto_update
    assert '"${GIT_SITE}/release-data.js"' in workflow
    assert '"$git_site"/release-data.js' in auto_update


def test_release_page_derives_history_and_current_version_independently() -> None:
    page = (REPO_ROOT / "成都修茈科技有限公司/download-releases.html").read_text()
    assert "fetchJson('/data/release-history.json')" in page
    assert "releases.history(projection.release_history)" in page
    assert "String(history.length)" in page
    assert "fetchJson('/download-release.json')" in page
    assert "release.version === current.version" in page
    assert "history[0]" not in page and "fallbackHistory" not in page
    assert "稳定版可下载" not in page
    assert "历史已发布（不代表当前可下载）" in page


def test_download_pages_share_bounded_interim_and_artifact_identity_validation() -> None:
    site = REPO_ROOT / "成都修茈科技有限公司"
    validator = (site / "release-data.js").read_text()
    for name in ("download.html", "download-releases.html"):
        page = (site / name).read_text()
        assert '<script src="/release-data.js"></script>' in page
        assert "releases.view(" in page
        assert "innerHTML" not in page
    assert "Date.parse(hotfix.risk_acceptance.expires_at) > Date.now()" in validator
    assert "hotfix.stable_auto_update !== false" in validator
    assert "hotfix.version !== version" in validator
    assert "manifest.git_sha !== pointer.git_sha" in validator
    assert "manifest.release_id !== pointer.release_id" in validator
    assert "Number.isSafeInteger(artifact.size)" in validator
    assert "artifact.url !== base + '/enterprise/' + hotfix.git_sha" in validator


def test_history_projection_preserves_canonical_records_without_rewriting_current_pointer() -> None:
    source = json.loads((REPO_ROOT / "FHD/config/download_release.json").read_text())
    history = json.loads((REPO_ROOT / "成都修茈科技有限公司/data/release-history.json").read_text())
    project = runpy.run_path(str(REPO_ROOT / "成都修茈科技有限公司/scripts/build_capability_center.py"))["public_projection"]
    assert history["release_history"] == project(source["release_history"], set())
    assert "太阳鸟行业考勤归并与企业交付可见" in [entry["title"] for entry in source["release_history"]]
    public_text = json.dumps(history, ensure_ascii=False).casefold()
    assert "太阳鸟" not in public_text and "sunbird" not in public_text
    page = (REPO_ROOT / "成都修茈科技有限公司/download-releases.html").read_text()
    assert "history.unshift" not in page and "hotfix.release" not in page
    assert "fetchJson('/download-windows-hotfix.json')" in page


def test_macos_release_builds_are_separate_from_authorized_frozen_pair_promotion() -> None:
    workflows = REPO_ROOT / "FHD/.github/workflows"
    build = (workflows / "release-desktop-mac-ota.yml").read_text()
    promote = (workflows / "fix-mac-update-feed.yml").read_text()
    legacy = (workflows / "publish-macos-download-center.yml").read_text()
    script = (REPO_ROOT / "FHD/scripts/package/publish-macos-download-center.sh").read_text()
    assert "default: true" in build and "Build-only lane" in build
    assert "publish-macos-download-center.sh" not in build
    assert "arm64_run_id:" in promote and "x64_run_id:" in promote
    assert "default: false" in promote and "verify_security_scan_pair.py" in promote
    assert "MACOS_FROZEN_PAIR_AUTHORIZED_SHA" in promote
    assert "exit 1" in legacy and "Use Fix macOS update feed" in legacy
    assert "ssh " not in legacy
    assert "release_ready == false" in script
    assert "--official-download-base" in script
    assert "--dry-run" in script and "XCAGI_MAC_PUBLICATION_AUTHORIZED_SHA" in script
