from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "merge-nginx-xiu-ci-snippets.py"
ADMIN_SNIPPET = Path(__file__).parents[1] / "nginx" / "snippets" / "admin-console-www.inc.conf"
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
    location = /download/ {
        return 302 /download;
    }
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
    assert "location = /download/" not in apex
    assert "include /etc/nginx/snippets/marketing-site-static.inc.conf;" in apex


def test_merge_is_idempotent() -> None:
    once = MODULE.merge_managed_includes(BASE_CONFIG)
    twice = MODULE.merge_managed_includes(once)

    assert twice == once
    assert twice.count("admin-console-www.inc.conf") == 1
    for include in MODULE.MANAGED_INCLUDES:
        assert twice.count(include) == 1


def test_crawler_summary_uses_tls_managed_route_and_replaces_old_inline_location() -> (
    None
):
    legacy = BASE_CONFIG.replace(
        "    location / { return 200; }",
        "    location = /llms.txt {\n        return 404;\n    }\n"
        "    location / { return 200; }",
    )
    merged = MODULE.merge_managed_includes(legacy)
    assert "location = /llms.txt" not in merged
    assert "marketing-site-static.inc.conf" in _block_for(merged, "xiu-ci.com")
    assert MODULE.merge_managed_includes(merged) == merged
    snippet = (ADMIN_SNIPPET.parent / "marketing-site-static.inc.conf").read_text()
    location = re.search(r"location = /llms\.txt \{([^}]+)\}", snippet)[1]
    assert "root /root/成都修茈科技有限公司;" in location
    assert "try_files $uri =404;" in location
    assert "default_type text/plain;" in location
    assert "charset utf-8;" in location


def test_admin_csp_runtime_exception_is_scoped_to_www_admin_spa() -> None:
    snippet = ADMIN_SNIPPET.read_text(encoding="utf-8")

    assert "location ^~ /admin/" in snippet
    assert "proxy_hide_header Content-Security-Policy;" in snippet
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in snippet
    assert "frame-src 'self'" in snippet
    assert "location / {\n    return 301 https://xiu-ci.com$request_uri;\n}" in snippet


def test_www_admin_serves_dashboard_without_cross_origin_redirect() -> None:
    snippet = ADMIN_SNIPPET.read_text(encoding="utf-8")

    assert "location ^~ /xcmax-dashboard/" in snippet
    dashboard = snippet.split("location ^~ /xcmax-dashboard/ {", 1)[1].split(
        "location = /admin", 1
    )[0]
    assert "if ($uri !~ " in dashboard and "return 404;" in dashboard
    assert "disable_symlinks on from=/root/XCMAX;" in dashboard
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in snippet


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("XCAGI-Full-Pipeline.html", True),
        ("XCAGI-Five-Line.html", True),
        ("docs/xcagi-dashboard/app.js", True),
        ("docs/xcagi-dashboard/dashboard.css", True),
        ("docs/xcagi-dashboard/vendor/dagre.min.js", True),
        (".cache/xcmax/xcmax-pytest-coverage.json", True),
        ("FHD/config/six_line_employee_map.json", True),
        ("FHD/docs/evidence/mod/01-listing.png", True),
        (".env", False),
        (".git/config", False),
        ("FHD/data/accounts.sqlite", False),
        ("FHD/app/config.py", False),
        ("downloads/customer.xlsx", False),
        ("docs/xcagi-dashboard/private.json", False),
        ("docs/xcagi-dashboard/vendor/private.js", False),
        ("FHD/docs/evidence/mod/private.png", False),
        ("docs/xcagi-dashboard/../../.env", False),
        ("XCAGI-Full-PipelineXhtml", False),
        ("XCAGI-Full-Pipeline.html\n", False),
    ],
)
def test_nginx_dashboard_uses_a_finite_asset_allowlist(path, allowed):
    snippet = ADMIN_SNIPPET.read_text(encoding="utf-8")
    pattern = re.search(r'if \(\$uri !~ "([^"]+)"\)', snippet)
    assert pattern is not None
    # PCRE's absolute-end \z is spelled \Z in Python's re (before Python 3.14).
    regex = pattern.group(1).replace(r"\z", r"\Z")
    assert bool(re.search(regex, "/xcmax-dashboard/" + path)) is allowed
