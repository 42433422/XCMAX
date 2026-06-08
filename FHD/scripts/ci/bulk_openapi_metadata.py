#!/usr/bin/env python3
"""验证 OpenAPI enrich 后元数据是否满足 --strict（不直接改源码，供 CI 辅助）。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate enriched OpenAPI metadata")
    parser.add_argument("--strict", action="store_true", help="Treat warn as failure")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    os.environ.setdefault("XCAGI_NEURO_INTENT", "1")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    checker = __import__(
        "scripts.ci.check_openapi_consistency",
        fromlist=["collect_openapi_operations", "check_operation_quality"],
    )
    from app.fastapi_app import get_fastapi_app

    app = get_fastapi_app()
    _ops, schema = checker.collect_openapi_operations(app)
    missing_desc = missing_schema = missing_tags = 0
    for _path, item in (schema.get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            if not op.get("tags"):
                missing_tags += 1
            if not op.get("description"):
                missing_desc += 1
            responses = op.get("responses") or {}
            has_schema = False
            for code, resp in responses.items():
                if not str(code).startswith("2"):
                    continue
                content = (resp or {}).get("content") or {}
                for media in content.values():
                    if isinstance(media, dict) and media.get("schema"):
                        has_schema = True
            if not has_schema:
                missing_schema += 1

    print(
        f"missing_tags={missing_tags} missing_description={missing_desc} "
        f"missing_response_schema={missing_schema}"
    )
    if args.strict and (missing_tags or missing_desc or missing_schema):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
