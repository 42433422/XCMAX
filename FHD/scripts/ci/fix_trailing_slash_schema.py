#!/usr/bin/env python3
"""一次性扫描：对运行时尾斜杠重复路由执行 schema 隐藏（调用共享 helper）。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Hide trailing-slash OpenAPI duplicates")
    parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    os.environ.setdefault("XCAGI_NEURO_INTENT", "1")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.fastapi_app import get_fastapi_app
    from app.fastapi_routes.openapi_route_compat import hide_trailing_slash_openapi_duplicates

    app = get_fastapi_app()
    hidden = hide_trailing_slash_openapi_duplicates(app)
    print(f"hidden_trailing_slash_routes={hidden}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
