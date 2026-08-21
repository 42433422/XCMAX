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
