#!/usr/bin/env python3
"""Ratchet: raw SQL debt in FHD/app (sqlalchemy text(f...) and f-string SQL)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = FHD_ROOT / "app"

# Bootstrap / vector DDL exceptions (documented in SQL_RAW_INVENTORY.md)
ALLOWLIST_SUFFIXES = (
    "app/db/init_db.py",
    "app/infrastructure/persistence/pg_vector_store.py",
    "app/infrastructure/persistence/sqlite_vector_store.py",
    "app/infrastructure/persistence/user_memory_vector_store.py",
    "app/security/license_store.py",
    # 表名来自可信模型常量 __tablename__，行数据全部走 :uid/:limit 绑定参数（无用户可控 SQL 拼接）。
    "app/infrastructure/persona/persona_repository_impl.py",
    # 模板多租户：WHERE 片段仅来自 templates_tenant_where_sql() 可信助手，绑定参数走 :id/:tenant。
    "app/application/excel_template_http_app_service.py",
    "app/fastapi_routes/document_templates_compat.py",
    "app/infrastructure/skills/template_manager/template_manager.py",
    "app/infrastructure/templates/template_store_impl.py",
    "app/services/document_templates/crud.py",
    # 迁移后 legacy compat 保有其原始 DDL 引导豁免。
    "app/legacy/routes/document_templates_compat.py",
    # init_db 拆分 part 与其母文件同类（schema/列引导 DDL）。
    "app/db/init_db_part03.py",
    "app/db/init_db_part03_part01.py",
    # Postgres schema 引导（CREATE SCHEMA / SHOW search_path，schema_name 来自可信参数）。
    "app/infrastructure/database/mod_schema_router.py",
)

TEXT_F_PATTERN = re.compile(r"\btext\s*\(\s*f[\"']", re.MULTILINE)
# 仅匹配单行 f-string 中的 SQL 关键字（[^"'\n] 不跨行），
# 避免误报 f"..." 后跨行撞上 Python 代码中的 from/where 等标识符。
FSQL_PATTERN = re.compile(
    r'f["\'][^"\'\n]*\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b',
    re.IGNORECASE,
)


def _rel(path: Path) -> str:
    return str(path.relative_to(FHD_ROOT)).replace("\\", "/")


def _is_allowlisted(rel: str) -> bool:
    return any(rel.endswith(suffix) for suffix in ALLOWLIST_SUFFIXES)


def scan_app() -> tuple[int, int, list[tuple[str, int, int]]]:
    text_f_total = 0
    fsql_total = 0
    per_file: list[tuple[str, int, int]] = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = _rel(path)
        if _is_allowlisted(rel):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        tf = len(TEXT_F_PATTERN.findall(content))
        fs = len(FSQL_PATTERN.findall(content))
        if tf or fs:
            per_file.append((rel, tf, fs))
            text_f_total += tf
            fsql_total += fs

    return text_f_total, fsql_total, per_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-text-f",
        type=int,
        default=0,
        help="Max allowed text(f...) hits outside allowlist (ratchet baseline 2026-06)",
    )
    parser.add_argument(
        "--max-fstring-sql",
        type=int,
        default=0,
        help="Max allowed f-string SQL hits outside allowlist",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    text_f, fsql, files = scan_app()
    score = text_f + fsql

    if args.verbose:
        print("file\ttext(f)\tfstring_sql")
        for rel, tf, fs in files:
            print(f"{rel}\t{tf}\t{fs}")
        print(f"TOTAL (excl allowlist)\ttext_f={text_f}\tfstring_sql={fsql}")

    print(f"raw_sql_score={score} (text_f={text_f}, fstring_sql={fsql})")

    if text_f > args.max_text_f or fsql > args.max_fstring_sql:
        print(
            f"FAIL: exceeds baseline (max text_f={args.max_text_f}, "
            f"max fstring_sql={args.max_fstring_sql})",
            file=sys.stderr,
        )
        return 1
    print("OK: within baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
