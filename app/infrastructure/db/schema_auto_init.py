"""从 ``pg_init_xcagi_core.sql`` 等脚本生成初始化 SQL 语句。

Phase 3B 从 ``app.legacy.schema_auto_init`` 吸收。原路径
``parents[1]/scripts/pg_init_xcagi_core.sql`` 是相对 ``app/legacy/`` 的
相对路径; 迁到 ``app/infrastructure/db/`` 后需要多跳一级,修正为
``parents[2]/scripts``,否则将读不到 SQL 文件。
"""

from __future__ import annotations

from pathlib import Path


def _load_init_sql_text() -> str:
    # app/infrastructure/db/schema_auto_init.py → parents = [db, infrastructure, app, <repo>]
    # scripts 在仓库根下,所以用 parents[3]/scripts。
    repo_root = Path(__file__).resolve().parents[3]
    p = repo_root / "scripts" / "pg_init_xcagi_core.sql"
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    return """
CREATE TABLE IF NOT EXISTS purchase_units (id BIGSERIAL PRIMARY KEY, unit_name TEXT);
CREATE INDEX IF NOT EXISTS idx_purchase_units_unit_name ON purchase_units(unit_name);
CREATE TABLE IF NOT EXISTS products (id BIGSERIAL PRIMARY KEY, name TEXT);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE TABLE IF NOT EXISTS customers (id BIGSERIAL PRIMARY KEY, customer_name TEXT);
CREATE INDEX IF NOT EXISTS idx_customers_customer_name ON customers(customer_name);
CREATE TABLE IF NOT EXISTS document_templates (id UUID PRIMARY KEY, slug TEXT);
CREATE INDEX IF NOT EXISTS idx_document_templates_slug ON document_templates(slug);
"""


def statements_from_init_sql(raw: str) -> list[str]:
    out: list[str] = []
    for chunk in (raw or "").split(";"):
        s = "\n".join(
            line
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ).strip()
        if not s:
            continue
        up = s.upper()
        if up in ("BEGIN", "COMMIT"):
            continue
        out.append(s + ";")
    return out


__all__ = ["_load_init_sql_text", "statements_from_init_sql"]
