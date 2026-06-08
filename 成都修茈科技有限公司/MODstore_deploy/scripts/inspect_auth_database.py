#!/usr/bin/env python3
"""核对 MODstore 认证所用数据源并抽样检查 users 表。

与 [`modstore_server.models.database_url`](../modstore_server/models.py) 一致：
优先 ``DATABASE_URL``，否则 SQLite（``MODSTORE_DB_PATH`` 或默认 ``modstore_server/modstore.db``）。

用法（在 MODstore_deploy 目录下）::

    python scripts/inspect_auth_database.py
    python scripts/inspect_auth_database.py --match admin
    python scripts/inspect_auth_database.py --match "@pytest"

退出码：0 成功；1 连接或查询失败；2 参数错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import urlparse, urlunparse

from sqlalchemy import or_


def _redact_database_url(url: str) -> str:
    if not url.startswith(("postgresql://", "postgres://")):
        return url
    try:
        parsed = urlparse(url if url.startswith("postgresql") else "postgresql" + url[len("postgres") :])
        if parsed.password:
            netloc = re.sub(r":([^:@]+)@", r":***@", parsed.netloc, count=1)
            parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)
    except Exception:
        return "postgresql://***"


def main() -> int:
    p = argparse.ArgumentParser(description="核对 DATABASE_URL 并查询 users 表抽样")
    p.add_argument(
        "--match",
        default="",
        help="可选：用户名或邮箱子串（不区分大小写），列出最多 20 条匹配",
    )
    p.add_argument("--limit", type=int, default=10, help="无 --match 时列出的用户行数上限（默认 10）")
    args = p.parse_args()
    lim = max(1, min(args.limit, 100))

    from modstore_server.models import User, database_url, get_engine, get_session_factory, init_db

    raw_url = database_url()
    print("resolved_engine_url:", _redact_database_url(raw_url))
    if raw_url.startswith("sqlite:///"):
        print("kind: sqlite")
    else:
        print("kind: postgresql")

    try:
        init_db()
        engine = get_engine()
        dialect = engine.dialect.name
        print("dialect:", dialect)
        with engine.connect() as conn:
            one = conn.exec_driver_sql("SELECT 1").scalar()
            print("connectivity: ok", f"(SELECT 1 -> {one!r})")
    except Exception as e:
        print("connectivity: FAILED", str(e), file=sys.stderr)
        return 1

    sf = get_session_factory()
    try:
        with sf() as session:
            total = session.query(User).count()
            print("users_total:", total)
            needle = (args.match or "").strip().lower()
            if needle:
                safe = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pat = f"%{safe}%"
                rows = (
                    session.query(User)
                    .filter(
                        or_(
                            User.username.ilike(pat, escape="\\"),
                            User.email.ilike(pat, escape="\\"),
                        )
                    )
                    .order_by(User.id.asc())
                    .limit(20)
                    .all()
                )
                print(f"match({needle!r}) count (capped 20):", len(rows))
                for u in rows:
                    em = u.email or ""
                    print(f"  id={u.id} username={u.username!r} email={em!r} is_admin={u.is_admin}")
            else:
                rows = session.query(User).order_by(User.id.asc()).limit(lim).all()
                print(f"sample_first_{lim}:")
                for u in rows:
                    em = u.email or ""
                    print(f"  id={u.id} username={u.username!r} email={em!r} is_admin={u.is_admin}")
    except Exception as e:
        print("query_users: FAILED", str(e), file=sys.stderr)
        return 1

    print()
    print("恢复提示：空库可设 MODSTORE_BOOTSTRAP_ADMIN；已有用户可用 scripts/grant_admin.py --reset-password")
    print("或 POST /api/admin/reset-user-password（需 MODSTORE_ADMIN_RECHARGE_TOKEN + X-Modstore-Recharge-Token）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
