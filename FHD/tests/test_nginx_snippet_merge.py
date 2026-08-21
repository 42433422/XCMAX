from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "scripts" / "merge-nginx-xiu-ci-snippets.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("merge_xiu_ci_snippets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_managed_includes_are_moved_out_of_nested_location_and_are_idempotent() -> None:
    module = _module()
    stale_include = module.MANAGED_INCLUDES[0]
    source = f"""
server {{
    listen 80;
    server_name xiu-ci.com;
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name xiu-ci.com www.xiu-ci.com;
    location / {{
        ## CORP_SITE_END
        {stale_include}
        try_files $uri /index.html;
    }}
}}
""".lstrip()

    merged = module.merge_managed_includes(source)
    assert module.merge_managed_includes(merged) == merged
    for include in module.MANAGED_INCLUDES:
        assert merged.count(include) == 1

    location_end = merged.index("    }", merged.index("location /"))
    include_position = merged.index(stale_include)
    server_end = merged.index("}", include_position)
    assert location_end < include_position < server_end


def test_merge_refuses_config_without_xiu_ci_server() -> None:
    module = _module()
    try:
        module.merge_managed_includes("server { server_name example.com; }\n")
    except ValueError as exc:
        assert "xiu-ci.com" in str(exc)
    else:
        raise AssertionError("expected missing xiu-ci.com server to fail closed")


def test_merge_repairs_orphaned_market_assets_block_from_legacy_deploy() -> None:
    module = _module()
    source = """
server {
    listen 443 ssl;
    server_name xiu-ci.com;

\t# market 静态 chunk：禁止落入 SPA index.html（避免旧 index 引用缺失 chunk 时 404/HTML 混乱）

            alias   /root/成都修茈科技有限公司/MODstore_deploy/market/dist/assets/;
            add_header  Cache-Control  "public, max-age=31536000, immutable";

\t}
    location = /download {
        try_files /download.html =404;
    }
}
""".lstrip()

    merged = module.merge_managed_includes(source)
    assert "market 静态 chunk" not in merged
    assert "alias /root/成都修茈科技有限公司/MODstore_deploy/market/dist/assets/;" not in merged
    assert "location = /download" in merged
    for include in module.MANAGED_INCLUDES:
        assert merged.count(include) == 1


def test_merge_rejects_unbalanced_config_after_known_repairs() -> None:
    module = _module()
    source = "server { listen 443 ssl; server_name xiu-ci.com; }\n}\n"
    try:
        module.merge_managed_includes(source)
    except ValueError as exc:
        assert "unbalanced" in str(exc)
    else:
        raise AssertionError("expected malformed nginx braces to fail closed")


def test_merge_removes_direct_xcagi_locations_owned_by_managed_snippet() -> None:
    module = _module()
    source = """
server {
    listen 443 ssl;
    server_name xiu-ci.com;
    location ~ ^/xcagi-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/ {
        root /var/www;
    }
    location = /download-release.json {
        alias /root/成都修茈科技有限公司/download-release.json;
        default_type application/json;
    }
    location /releases/stable/ {
        root /var/www/update;
    }
}
""".lstrip()

    merged = module.merge_managed_includes(source)
    assert "location ~ ^/xcagi-v" not in merged
    assert "location = /download-release.json" not in merged
    assert "location /releases/stable/" not in merged
    assert merged.count("xcagi-cos-alias.inc.conf") == 1


def test_every_managed_snippet_location_has_a_direct_block_cleanup_contract() -> None:
    module = _module()
    snippet_dir = REPO_ROOT / "成都修茈科技有限公司" / "deploy" / "nginx" / "snippets"
    managed_snippets = (
        "marketing-site-static.inc.conf",
        "corp-main-styles.inc.conf",
        "xcagi-cos-alias.inc.conf",
        "market-static.inc.conf",
        "founder-autonomy-admin.inc.conf",
    )
    headers = []
    for name in managed_snippets:
        headers.extend(
            line
            for line in (snippet_dir / name).read_text(encoding="utf-8").splitlines()
            if line.startswith("location ")
        )

    assert headers
    assert all(module._is_managed_location(header) for header in headers)


def test_merge_removes_market_and_site_routes_before_including_snippets() -> None:
    module = _module()
    source = """
server {
    listen 443 ssl;
    server_name xiu-ci.com;
    location = /market {
        return 301 /market/;
    }
    location /market/ {
        alias /legacy/market/;
    }
    location = /site/main.js {
        alias /legacy/main.js;
    }
    location ~ ^/(styles\\.css|main\\.js|contact-intake\\.js|contact-channels\\.js|visualization\\.js|world-will\\.js|world-will-ticker\\.js|world-will-ticker\\.css)$ {
        root /legacy/site;
    }
}
""".lstrip()

    merged = module.merge_managed_includes(source)
    assert "location = /market" not in merged
    assert "location /market/" not in merged
    assert "location = /site/main.js" not in merged
    assert "location ~ ^/(styles\\.css" not in merged
    assert merged.count("market-static.inc.conf") == 1
    assert merged.count("marketing-site-static.inc.conf") == 1
