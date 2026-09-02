from __future__ import annotations

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
    assert "xcagi-v8.0.0" not in snippet
    assert "alias /root/成都修茈科技有限公司/download-release.json;" in snippet
    assert "alias /root/成都修茈科技有限公司/download-windows-hotfix.json;" in snippet


def test_standalone_vhost_uses_the_same_versioned_public_download_contract() -> None:
    config = (REPO_ROOT / "成都修茈科技有限公司" / "nginx-xiu-ci-root.conf").read_text(
        encoding="utf-8"
    )

    assert "location ~ ^/xcagi-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/" in config
    assert "{3}" not in config
    assert "location ^~ /xcagi-v1.0.0.0/" not in config
    assert "alias /root/成都修茈科技有限公司/download-release.json;" in config
    assert "alias /root/成都修茈科技有限公司/download-windows-hotfix.json;" in config


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

    assert '[ ! -e "${LIVE_SITE}/download-release.json" ]' in workflow
    assert "preserving release-managed download-release.json" in workflow
    assert "preserving release-managed download-windows-hotfix.json" in workflow
    assert (
        '[[ ! -e "$live_site/download-release.json" && -f "$git_site/download-release.json" ]]'
        in auto_update
    )
    assert "保留发布流程管理的 download-release.json" in auto_update
    assert "保留发布流程管理的 download-windows-hotfix.json" in auto_update


def test_release_page_uses_public_history_order_for_the_current_version() -> None:
    release_page = (REPO_ROOT / "成都修茈科技有限公司" / "download-releases.html").read_text(
        encoding="utf-8"
    )

    assert "fetchJson('/download-release.json')" in release_page
    assert "history.forEach(function (release, releaseIndex)" in release_page
    assert "if (releaseIndex === 0) entry.className += ' is-current'" in release_page
    assert "if (releaseVersion === '1.0.0.0') entry.className += ' is-current'" not in release_page
    assert "fetchJson('/download-windows-hotfix.json')" in release_page
    assert "Windows 临时交付可下载" in release_page


def test_download_page_prefers_a_same_or_newer_explicit_unsigned_interim_pointer() -> None:
    download_page = (REPO_ROOT / "成都修茈科技有限公司" / "download.html").read_text(
        encoding="utf-8"
    )

    assert "fetch('/download-windows-hotfix.json', { cache: 'no-store' })" in download_page
    assert "hotfix.signature_status !== 'unsigned'" in download_page
    assert "compareVersions(hotfix.version, state.version) >= 0" in download_page
    assert "Boolean(manifestEntry(row.platform))" in download_page
    assert "row.platform === 'android' && Boolean(state.androidVersion)" in download_page
    assert "下载临时包" in download_page
    assert "不会进入稳定自动更新" in download_page


def test_release_page_keeps_same_version_windows_interim_visible() -> None:
    release_page = (REPO_ROOT / "成都修茈科技有限公司" / "download-releases.html").read_text(
        encoding="utf-8"
    )

    assert "compareVersions(hotfix.version, history[0].version) >= 0" in release_page
    assert "太阳鸟行业考勤归并与企业交付可见" in release_page


def test_macos_release_flow_publishes_download_center_metadata_and_has_recovery_path() -> None:
    mac_workflow = (
        REPO_ROOT / "FHD" / ".github" / "workflows" / "release-desktop-mac-ota.yml"
    ).read_text(encoding="utf-8")
    recovery_workflow = (
        REPO_ROOT / "FHD" / ".github" / "workflows" / "publish-macos-download-center.yml"
    ).read_text(encoding="utf-8")
    publish_script = (
        REPO_ROOT / "FHD" / "scripts" / "package" / "publish-macos-download-center.sh"
    ).read_text(encoding="utf-8")

    assert "Publish download center metadata and changelog" in mac_workflow
    assert "publish-macos-download-center.sh" in mac_workflow
    assert "source_run_id:" in recovery_workflow
    assert "gh run download" in recovery_workflow
    assert "publish-macos-download-center.sh" in recovery_workflow
    assert "release_ready == false" in publish_script
    assert 'contains("太阳鸟")' in publish_script
    assert "chmod a+rx" in publish_script
    assert "download-release.json" in publish_script
    assert "download/releases?release-run=" in publish_script
