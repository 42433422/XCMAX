#!/usr/bin/env python3
"""将 ``catalog_data/packages.json`` 登记同步到市场库 ``catalog_items``（与
``POST /api/admin/catalog/sync-from-xc-packages`` 同逻辑）。

在远端服务器上：先部署/更新含目标包条目的 ``packages.json`` 与
``catalog_data/files/<*.xcemp>``，再于 ``MODstore_deploy`` 根目录执行本脚本，最后重启
API 进程。环境变量 ``MODSTORE_CATALOG_DIR``、``DATABASE_URL`` 与运行时一致。

用法::

    cd /path/to/MODstore_deploy
    PYTHONPATH=. python scripts/sync_catalog_from_xc_packages.py
    PYTHONPATH=. python scripts/sync_catalog_from_xc_packages.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync XC packages.json into catalog_items")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run upserts then rollback (no commit)",
    )
    args = parser.parse_args()

    from modstore_server.catalog_sync import sync_packages_json_to_catalog_items
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        admin = (
            session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
        )  # noqa: E712
        admin = admin or session.query(User).order_by(User.id.asc()).first()
        if admin is None:
            print("No user in database; cannot assign author_id.", file=sys.stderr)
            return 3
        out = sync_packages_json_to_catalog_items(session, admin_user_id=int(admin.id))
        if args.dry_run:
            session.rollback()
            out = dict(out)
            out["dry_run"] = True
        else:
            session.commit()
            out = dict(out)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
