#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为每个扩展（Mod）在 PostgreSQL 上创建独立业务库，并启用 pgvector。

与 backend/mod_database_url.py 中 XCAGI_MOD_ISOLATED_DATABASES=1 时的命名一致：
  {基库名}__{mod_id 规范化小写后缀}

Mod 列表来源（按优先级）：
  1. 环境变量 XCAGI_MOD_DATABASE_URLS 的 JSON 键
  2. 环境变量 XCAGI_MOD_IDS（逗号分隔）
  3. 扫描 XCAGI_ROOT 或 XCAGI_MODS_DIR 下 mods/*/manifest.json 的 id 字段

用法（在 XCAGI 仓库根目录）:
  set XCAGI_MOD_ISOLATED_DATABASES=1
  python scripts/bootstrap_mod_postgres_databases.py

随后对每个新库执行迁移（推荐一键）:
  python scripts/migrate_mod_postgres_databases.py

或单库示例:
  DATABASE_URL=postgresql+psycopg://.../xcagi__my_mod python -m alembic upgrade head
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass


def _normalize_mod_file_suffix(mod_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(mod_id or "").strip()).strip("_").lower()


def _discover_mod_ids() -> list[str]:
    raw_json = (os.environ.get("XCAGI_MOD_DATABASE_URLS") or "").strip()
    if raw_json:
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict):
                keys = [str(k).strip() for k in obj if str(k).strip()]
                if keys:
                    return sorted(set(keys))
        except json.JSONDecodeError:
            pass
    csv = (os.environ.get("XCAGI_MOD_IDS") or "").strip()
    if csv:
        return sorted({p.strip() for p in csv.split(",") if p.strip()})
    roots: list[Path] = []
    for key in ("XCAGI_MODS_DIR", "XCAGI_ROOT"):
        v = (os.environ.get(key) or "").strip()
        if v:
            roots.append(Path(v).resolve())
    if not roots and Path(_ROOT, "mods").is_dir():
        roots.append(Path(_ROOT, "mods").resolve())
    seen: set[str] = set()
    out: list[str] = []
    for base in roots:
        mods_dir = base if base.name == "mods" else base / "mods"
        if not mods_dir.is_dir():
            continue
        for child in sorted(mods_dir.iterdir()):
            if not child.is_dir():
                continue
            mf = child / "manifest.json"
            if not mf.is_file():
                continue
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            mid = str((data or {}).get("id") or "").strip()
            if mid and mid not in seen:
                seen.add(mid)
                out.append(mid)
    return sorted(out)


def _maintenance_engine(base_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    u = make_url(base_url)
    if u.get_backend_name() != "postgresql":
        raise SystemExit("ERROR: DATABASE_URL must be PostgreSQL.")
    admin = u.set(database="postgres")
    return create_engine(admin, isolation_level="AUTOCOMMIT", future=True)


def main() -> int:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if not (url.startswith("postgresql") or url.startswith("postgres")):
        print("ERROR: DATABASE_URL must be a PostgreSQL URL.", file=sys.stderr)
        return 1

    mod_ids = _discover_mod_ids()
    if not mod_ids:
        print(
            "No mod ids found. Set XCAGI_MOD_DATABASE_URLS, XCAGI_MOD_IDS, or install manifests under mods/.",
            file=sys.stderr,
        )
        return 1

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    base_u = make_url(url)
    base_db = (base_u.database or "xcagi").strip()

    admin_engine = _maintenance_engine(url)
    created: list[str] = []
    with admin_engine.connect() as conn:
        for mid in mod_ids:
            suf = _normalize_mod_file_suffix(mid)
            if not suf:
                continue
            dbn = f"{base_db}__{suf}"
            row = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": dbn},
            ).fetchone()
            if row:
                print(f"SKIP exists: {dbn}")
                continue
            owner = base_u.username or None
            if owner:
                conn.execute(text(f'CREATE DATABASE "{dbn}" OWNER "{owner}"'))
            else:
                conn.execute(text(f'CREATE DATABASE "{dbn}"'))
            created.append(dbn)
            print(f"OK CREATE DATABASE {dbn}")
    admin_engine.dispose()

    for dbn in created:
        mod_url = str(base_u.set(database=dbn))
        try:
            eng = create_engine(mod_url, isolation_level="AUTOCOMMIT", future=True)
            with eng.connect() as c:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            eng.dispose()
            print(f"OK vector extension: {dbn}")
        except Exception as e:
            print(
                f"WARN: could not enable vector on {dbn} ({e}). "
                f"Fix DATABASE_URL credentials then run: "
                f'psql "{mod_url}" -c "CREATE EXTENSION IF NOT EXISTS vector;"',
                file=sys.stderr,
            )

    print("Next: python scripts/migrate_mod_postgres_databases.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
