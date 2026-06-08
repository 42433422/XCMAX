#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对 ``XCAGI_MOD_ISOLATED_DATABASES=1`` 下各扩展库 ``{基库名}__<mod>`` 依次执行 ``alembic upgrade head``。

用法（在 XCAGI 仓库根目录，已配置 DATABASE_URL 指向基库，且已运行 bootstrap_mod_postgres_databases.py）:

  python scripts/migrate_mod_postgres_databases.py

Mod 列表发现规则与 bootstrap_mod_postgres_databases.py 一致。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_bootstrap():
    path = _ROOT / "scripts" / "bootstrap_mod_postgres_databases.py"
    spec = importlib.util.spec_from_file_location("xcagi_bootstrap_mod_pg", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bootstrap_mod_postgres_databases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env")
    except ImportError:
        pass

    boot = _load_bootstrap()
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url.startswith("postgres"):
        print("ERROR: DATABASE_URL must be PostgreSQL.", file=sys.stderr)
        return 1
    if (os.environ.get("XCAGI_MOD_ISOLATED_DATABASES") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(
            "WARN: XCAGI_MOD_ISOLATED_DATABASES is not enabled; "
            "migrating per-mod DBs is usually unnecessary.",
            file=sys.stderr,
        )

    mod_ids = boot._discover_mod_ids()
    if not mod_ids:
        print(
            "ERROR: No mod ids found (XCAGI_MOD_DATABASE_URLS / XCAGI_MOD_IDS / mods/*/manifest.json).",
            file=sys.stderr,
        )
        return 1

    from sqlalchemy.engine import make_url

    base_u = make_url(url)
    base_db = (base_u.database or "xcagi").strip()
    alembic_ini = _ROOT / "alembic.ini"
    if not alembic_ini.is_file():
        print("ERROR: alembic.ini not found.", file=sys.stderr)
        return 1

    rc = 0
    for mid in mod_ids:
        suf = boot._normalize_mod_file_suffix(mid)
        if not suf:
            continue
        dbn = f"{base_db}__{suf}"
        mod_url = str(base_u.set(database=dbn))
        print(f"==> alembic upgrade head  ->  {dbn}")
        env = os.environ.copy()
        env["DATABASE_URL"] = mod_url
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
            cwd=str(_ROOT),
            env=env,
        )
        if r.returncode != 0:
            rc = r.returncode
            print(f"FAILED: {dbn} (exit {r.returncode})", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
