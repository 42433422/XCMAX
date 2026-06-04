#!/usr/bin/env python3
"""将 crm.sqlite3 中 cs_delivery_signoffs 迁移至 PostgreSQL。

用法（在 FHD 目录）：
  CS_SIGNOFF_BACKEND=postgres DATABASE_URL=... python3 scripts/migrate_cs_delivery_signoffs_sqlite_to_postgres.py --dry-run
  CS_SIGNOFF_BACKEND=postgres DATABASE_URL=... python3 scripts/migrate_cs_delivery_signoffs_sqlite_to_postgres.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _sqlite_path() -> Path:
    from app.infrastructure.cs.delivery_signoff_sqlite import _db_path

    return _db_path()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("specify --dry-run or --apply")

    path = _sqlite_path()
    if not path.is_file():
        print(f"No sqlite file at {path}")
        return 0

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM cs_delivery_signoffs ORDER BY id").fetchall()
    conn.close()
    print(f"Found {len(rows)} signoff rows in {path}")

    if args.dry_run:
        for r in rows[:5]:
            print(dict(r))
        return 0

    from app.db.models.cs_delivery_signoff import CsDeliverySignoff
    from app.db.session import get_db

    migrated = 0
    with get_db() as db:
        for r in rows:
            existing = db.get(CsDeliverySignoff, int(r["id"]))
            if existing:
                continue
            db.add(
                CsDeliverySignoff(
                    id=int(r["id"]),
                    opportunity_id=int(r["opportunity_id"]),
                    market_user_id=int(r["market_user_id"]),
                    status=str(r["status"] or "pending"),
                    signed_by=str(r["signed_by"] or "")[:128],
                    signed_role=str(r["signed_role"] or "customer")[:32],
                    attachment_url=str(r["attachment_url"] or "")[:512],
                    notes=str(r["notes"] or "")[:8000],
                    created_at=_parse_iso(r["created_at"]) or datetime.utcnow(),
                    signed_at=_parse_iso(r["signed_at"]),
                )
            )
            migrated += 1
        if migrated:
            from sqlalchemy import text

            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('cs_delivery_signoffs', 'id'), "
                    "(SELECT COALESCE(MAX(id), 1) FROM cs_delivery_signoffs))"
                )
            )
    print(f"Migrated {migrated} rows into PostgreSQL cs_delivery_signoffs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
