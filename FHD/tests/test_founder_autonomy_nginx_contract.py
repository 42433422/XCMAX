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
    assert "proxy_pass http://127.0.0.1:5100;" in snippet
    assert "proxy_set_header Cookie $http_cookie;" in snippet
    assert "proxy_set_header Authorization $http_authorization;" in snippet


def test_nginx_sync_installs_founder_cockpit_snippet() -> None:
    sync_script = (
        REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "scripts" / "sync-nginx-xiu-ci-snippets.sh"
    ).read_text(encoding="utf-8")

    assert "founder-autonomy-admin.inc.conf" in sync_script
    assert "include /etc/nginx/snippets/founder-autonomy-admin.inc.conf;" in sync_script
