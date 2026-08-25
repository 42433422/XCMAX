from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "merge-nginx-xiu-ci-snippets.py"
SPEC = importlib.util.spec_from_file_location("merge_nginx_xiu_ci_snippets", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


BASE_CONFIG = """
server {
    listen 80;
    server_name www.xiu-ci.com xiu-ci.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name www.xiu-ci.com;
    ssl_certificate /etc/nginx/ssl/xiu-ci.com.crt;
    return 301 https://xiu-ci.com$request_uri;
}

server {
    listen 443 ssl http2;
    server_name xiu-ci.com;
    ssl_certificate /etc/nginx/ssl/xiu-ci.com.crt;
    location / { return 200; }
}
""".lstrip()


def _block_for(text: str, hostname: str) -> str:
    lines = text.splitlines()
    for start, end in MODULE._server_blocks(lines):
        if MODULE._server_names(lines, start, end) == {hostname}:
            return "\n".join(lines[start : end + 1])
    raise AssertionError(f"missing server block for {hostname}")


def test_full_admin_isolated_on_www_and_apex_includes_remain_separate() -> None:
    merged = MODULE.merge_managed_includes(BASE_CONFIG)
    www = _block_for(merged, "www.xiu-ci.com")
    apex = _block_for(merged, "xiu-ci.com")

    assert "include /etc/nginx/snippets/admin-console-www.inc.conf;" in www
    assert "return 301 https://xiu-ci.com$request_uri;" not in www
    assert "founder-autonomy-admin.inc.conf" not in www

    assert "include /etc/nginx/snippets/founder-autonomy-admin.inc.conf;" in apex
    assert "admin-console-www.inc.conf" not in apex


def test_merge_is_idempotent() -> None:
    once = MODULE.merge_managed_includes(BASE_CONFIG)
    twice = MODULE.merge_managed_includes(once)

    assert twice == once
    assert twice.count("admin-console-www.inc.conf") == 1
    for include in MODULE.MANAGED_INCLUDES:
        assert twice.count(include) == 1
