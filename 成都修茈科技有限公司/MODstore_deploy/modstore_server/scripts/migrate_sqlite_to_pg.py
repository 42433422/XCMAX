"""SQLite + JSON 订单迁移到 PostgreSQL。

目标库表结构应先由 Flyway/Alembic/SQLAlchemy 创建；本脚本只搬迁数据并输出对账摘要。

用法:
  set SQLITE_PATH=path\\to\\modstore.db
  set DATABASE_URL=postgresql://user:pass@host:5432/dbname
  set MODSTORE_PAYMENT_ORDERS_DIR=path\\to\\payment_orders
  python -m modstore_server.scripts.migrate_sqlite_to_pg
"""

from __future__ import annotations

import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

TABLES = [
    "users",
    "verification_codes",
    "wallets",
    "transactions",
    "catalog_items",
    "purchases",
    "user_mods",
    "workflows",
    "workflow_nodes",
    "workflow_edges",
    "user_llm_credentials",
    "workflow_executions",
    "plan_templates",
    "user_plans",
    "quotas",
    "entitlements",
    "employee_execution_metrics",
    "workflow_triggers",
    "notifications",
    "reviews",
    "favorites",
    "refund_requests",
]

ORDER_COLUMNS = [
    "out_trade_no",
    "trade_no",
    "user_id",
    "subject",
    "total_amount",
    "order_kind",
    "item_id",
    "plan_id",
    "status",
    "buyer_id",
    "paid_at",
    "fulfilled",
    "qr_code",
    "pay_type",
    "created_at",
    "updated_at",
]


def _pg_url() -> str:
    pg_url = os.environ.get("DATABASE_URL", "").strip()
    if pg_url.startswith("postgres://"):
        return "postgresql://" + pg_url[len("postgres://") :]
    return pg_url


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _payment_orders_dir() -> Path | None:
    raw = (os.environ.get("MODSTORE_PAYMENT_ORDERS_DIR") or "").strip()
    if raw:
        return Path(raw)
    default_dir = Path(__file__).resolve().parents[1] / "payment_orders"
    return default_dir if default_dir.exists() else None


def _insert_rows(pg, table: str, cols: list[str], rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    col_names = ", ".join(f'"{c}"' for c in cols)
    conflict = " ON CONFLICT DO NOTHING"
    sql = f'INSERT INTO "{table}" ({col_names}) VALUES %s{conflict}'
    with pg.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
        return cur.rowcount if cur.rowcount >= 0 else len(rows)


def _migrate_table(sq: sqlite3.Connection, pg, table: str) -> dict[str, int]:
    try:
        sqlite_rows = sq.execute(f'SELECT * FROM "{table}"').fetchall()
    except sqlite3.OperationalError:
        return {"source": 0, "inserted": 0, "skipped": 1}
    if not sqlite_rows:
        return {"source": 0, "inserted": 0, "skipped": 0}
    cols = list(sqlite_rows[0].keys())
    rows = [tuple(row[c] for c in cols) for row in sqlite_rows]
    inserted = _insert_rows(pg, table, cols, rows)
    return {"source": len(rows), "inserted": inserted, "skipped": 0}


def _json_order_row(doc: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        [
            doc.get("out_trade_no"),
            doc.get("trade_no"),
            int(doc.get("user_id") or 0),
            doc.get("subject") or "XC AGI 订单",
            _money(doc.get("total_amount")),
            doc.get("order_kind")
            or ("item" if doc.get("item_id") else "plan" if doc.get("plan_id") else "wallet"),
            int(doc.get("item_id") or 0) or None,
            doc.get("plan_id") or None,
            doc.get("status") or "pending",
            doc.get("buyer_id"),
            doc.get("paid_at"),
            bool(doc.get("fulfilled")),
            doc.get("qr_code"),
            doc.get("pay_type"),
            doc.get("created_at"),
            doc.get("updated_at"),
        ]
    )


def _migrate_json_orders(pg) -> dict[str, int]:
    orders_dir = _payment_orders_dir()
    if not orders_dir or not orders_dir.exists():
        return {"source": 0, "inserted": 0, "skipped": 0}
    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for path in orders_dir.glob("order_*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not doc.get("out_trade_no") or not int(doc.get("user_id") or 0):
                skipped += 1
                continue
            rows.append(_json_order_row(doc))
        except Exception:
            skipped += 1
    inserted = _insert_rows(pg, "orders", ORDER_COLUMNS, rows)
    return {"source": len(rows), "inserted": inserted, "skipped": skipped}


def _count_pg(pg, table: str) -> int:
    try:
        with pg.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            return int(cur.fetchone()[0])
    except Exception:
        pg.rollback()
        return -1


def main() -> None:
    sqlite_path = os.environ.get("SQLITE_PATH", "").strip()
    pg_url = _pg_url()
    if not sqlite_path or not pg_url:
        print("请设置 SQLITE_PATH 与 DATABASE_URL")
        return
    try:
        import psycopg2
    except ImportError:
        print("请安装: pip install psycopg2-binary")
        return

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    pg = psycopg2.connect(pg_url)
    pg.autocommit = False
    report: dict[str, dict[str, int]] = {}
    for table in TABLES:
        try:
            report[table] = _migrate_table(sq, pg, table)
            pg.commit()
        except Exception as e:
            pg.rollback()
            report[table] = {"source": 0, "inserted": 0, "skipped": 1}
            print(f"  {table}: error {e}")
    try:
        report["orders_json"] = _migrate_json_orders(pg)
        pg.commit()
    except Exception as e:
        pg.rollback()
        report["orders_json"] = {"source": 0, "inserted": 0, "skipped": 1}
        print(f"  orders_json: error {e}")

    print("迁移摘要:")
    for table, row in report.items():
        target_count = _count_pg(pg, "orders" if table == "orders_json" else table)
        print(
            f"  {table}: source={row['source']} inserted={row['inserted']} "
            f"skipped={row['skipped']} target_count={target_count}"
        )
    sq.close()
    pg.close()
    print("完成")


if __name__ == "__main__":
    main()
