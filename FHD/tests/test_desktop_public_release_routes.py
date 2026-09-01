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


def test_standalone_vhost_uses_the_same_versioned_public_download_contract() -> None:
    config = (REPO_ROOT / "成都修茈科技有限公司" / "nginx-xiu-ci-root.conf").read_text(
        encoding="utf-8"
    )

    assert "location ~ ^/xcagi-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/" in config
    assert "{3}" not in config
    assert "location ^~ /xcagi-v1.0.0.0/" not in config
    assert "alias /root/成都修茈科技有限公司/download-release.json;" in config


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
    assert (
        '[[ ! -e "$live_site/download-release.json" && -f "$git_site/download-release.json" ]]'
        in auto_update
    )
    assert "保留发布流程管理的 download-release.json" in auto_update


def test_release_page_uses_public_history_order_for_the_current_version() -> None:
    release_page = (
        REPO_ROOT / "成都修茈科技有限公司" / "download-releases.html"
    ).read_text(encoding="utf-8")

    assert "fetch('/download-release.json', { cache: 'no-store' })" in release_page
    assert "history.forEach(function (release, releaseIndex)" in release_page
    assert "if (releaseIndex === 0) entry.className += ' is-current'" in release_page
    assert "if (releaseVersion === '1.0.0.0') entry.className += ' is-current'" not in release_page
