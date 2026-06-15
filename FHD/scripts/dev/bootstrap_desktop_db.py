#!/usr/bin/env python3
"""桌面 SQLite 库幂等初始化（users/sessions/IM 等宿主表）。

用法（企业开发）:
  export XCAGI_DESKTOP_MODE=1
  export XCAGI_DATA_DIR=/path/to/XCAGI/data/desktop-dev
  python FHD/scripts/dev/bootstrap_desktop_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))


def main() -> int:
    os.environ.setdefault("XCAGI_DESKTOP_MODE", "1")
    data_dir = os.environ.get("XCAGI_DATA_DIR")
    if not data_dir:
        data_dir = str(FHD_ROOT / "XCAGI" / "data" / "desktop-dev")
        os.environ["XCAGI_DATA_DIR"] = data_dir

    from app.db import get_host_engine
    from app.db.init_db import (
        ensure_desktop_sqlite_business_tables_all_files,
        ensure_runtime_auth_bootstrap,
        ensure_runtime_database_environment,
        init_approval_tables,
        init_im_tables,
        init_service_bridge_tables,
        initialize_databases,
    )
    from app.fastapi_app.sqlite_paths import is_sqlite_url

    url = ensure_runtime_database_environment()
    if not is_sqlite_url(url):
        print(f"[ERR] 期望 SQLite URL，当前为: {url}", file=sys.stderr)
        return 1

    print(f"[1/5] DATABASE_URL={url}")
    initialize_databases()
    print("[2/5] 业务种子库检查完成")
    ensure_desktop_sqlite_business_tables_all_files(data_dir=data_dir)
    print("[3/5] products/purchase_units/customers 业务表已补齐")
    engine = get_host_engine()
    ensure_runtime_auth_bootstrap(engine, database_url=url)
    print("[4/5] users/sessions/RBAC 已补齐")
    init_approval_tables(engine)
    init_service_bridge_tables(engine)
    init_im_tables(engine, database_url=url)
    print("[5/5] approval / service_bridge / IM 表已补齐")
    print("[OK] 桌面数据库初始化完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
