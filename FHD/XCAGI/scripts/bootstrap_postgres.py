#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新 PostgreSQL 库一次性准备：启用 pgvector 扩展。

用法（在 XCAGI 仓库根目录）:
  python scripts/bootstrap_postgres.py

依赖环境变量 DATABASE_URL（与 app 一致，推荐 postgresql+psycopg://...）。
需要具备在该库上执行 CREATE EXTENSION 的权限（通常为超级用户或已授予的 role）。

随后请执行:
  python -m alembic upgrade head
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass


def main() -> int:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if not (url.startswith("postgresql") or url.startswith("postgres")):
        print("ERROR: DATABASE_URL must be a PostgreSQL URL.", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine, text

    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    engine.dispose()
    print("OK: CREATE EXTENSION IF NOT EXISTS vector")
    print("Next: python -m alembic upgrade head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
