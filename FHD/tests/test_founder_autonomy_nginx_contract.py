from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_founder_cockpit_nginx_snippet_preserves_auth_boundary() -> None:
    snippet = (
        REPO_ROOT
        / "成都修茈科技有限公司"
        / "deploy"
        / "nginx"
        / "snippets"
        / "founder-autonomy-admin.inc.conf"
    ).read_text(encoding="utf-8")

    assert "location = /admin/founder-autonomy" in snippet
    assert "location ^~ /admin/assets/" in snippet
    assert "location = /api/xcmax/ops/founder-autonomy" in snippet
    assert "location = /download-founder-autonomy.json" in snippet
    assert "root /var/lib/xcmax-public;" in snippet
    assert "try_files /download-founder-autonomy.json =404;" in snippet
    assert "default_type application/json;" in snippet
    assert "proxy_pass http://127.0.0.1:5100;" in snippet
    assert "proxy_set_header Cookie $http_cookie;" in snippet
    assert "proxy_set_header Authorization $http_authorization;" in snippet


def test_nginx_sync_installs_founder_cockpit_snippet() -> None:
    sync_script = (
        REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "scripts" / "sync-nginx-xiu-ci-snippets.sh"
    ).read_text(encoding="utf-8")
    merge_script = (
        REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "scripts" / "merge-nginx-xiu-ci-snippets.py"
    ).read_text(encoding="utf-8")

    assert "founder-autonomy-admin.inc.conf" in sync_script
    assert "include /etc/nginx/snippets/founder-autonomy-admin.inc.conf;" in merge_script


def test_immutable_release_preserves_public_founder_projection() -> None:
    release_script = (
        REPO_ROOT
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "scripts"
        / "xcmax-immutable-release.sh"
    ).read_text(encoding="utf-8")

    assert "XCMAX_PUBLIC_SITE_STATE_DIR:-/var/lib/xcmax-public" in release_script
    assert 'install -d -m 755 "$PUBLIC_SITE_STATE_DIR"' in release_script
    assert (
        'PUBLIC_PROJECTION_PATH="${PUBLIC_SITE_STATE_DIR}/download-founder-autonomy.json"'
        in release_script
    )
    assert "seeded persistent public founder projection" in release_script
