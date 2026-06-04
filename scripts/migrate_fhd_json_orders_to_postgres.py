#!/usr/bin/env python3
"""将 FHD 本地 model_payment_orders.json 幂等导入 PostgreSQL。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _load_json_store(path: Path) -> tuple[dict, dict]:
    if not path.is_file():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}, {}
    orders = data.get("orders") if isinstance(data.get("orders"), dict) else {}
    ents = data.get("entitlements") if isinstance(data.get("entitlements"), dict) else {}
    return orders, ents


def migrate(*, dry_run: bool, archive_json: bool) -> int:
    store = _REPO / "data" / "model_payment_orders.json"
    orders, ents = _load_json_store(store)
    if not orders and not ents:
        print("no local JSON orders/entitlements to migrate")
        return 0

    print(f"JSON orders={len(orders)} entitlements={len(ents)}")
    if dry_run:
        return 0

    sys.path.insert(0, str(_REPO))
    from app.db.models.model_payment import ModelPaymentEntitlement, ModelPaymentOrder
    from app.db.session import get_db

    upserted_orders = 0
    upserted_ents = 0
    with get_db() as db:
        for out_trade_no, o in orders.items():
            if not isinstance(o, dict):
                continue
            otn = str(o.get("out_trade_no") or out_trade_no)
            row = (
                db.query(ModelPaymentOrder)
                .filter(ModelPaymentOrder.out_trade_no == otn)
                .first()
            )
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            paid_at = _parse_iso(o.get("paid_at"))
            created = _parse_iso(o.get("created_at")) or now
            fields = {
                "plan_id": str(o.get("plan_id") or ""),
                "amount_cents": int(o.get("amount_cents") or 0),
                "amount_yuan": str(o.get("amount_yuan") or "0.00"),
                "status": str(o.get("status") or "pending_payment"),
                "trade_no": o.get("trade_no"),
                "market_user_id": int(o["market_user_id"]) if o.get("market_user_id") else None,
                "notify_count": int(o.get("notify_count") or 0),
                "last_notify_at": _parse_iso(o.get("last_notify_at")),
                "paid_at": paid_at,
                "updated_at": now,
            }
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
            else:
                db.add(
                    ModelPaymentOrder(
                        out_trade_no=otn,
                        created_at=created,
                        **fields,
                    )
                )
            upserted_orders += 1

        for plan_id, ent in ents.items():
            if not isinstance(ent, dict):
                continue
            pid = str(ent.get("plan_id") or plan_id)
            row = db.get(ModelPaymentEntitlement, pid)
            if row is None:
                row = ModelPaymentEntitlement(plan_id=pid, purchase_count=0)
                db.add(row)
            row.purchase_count = int(ent.get("purchase_count") or row.purchase_count or 0)
            row.first_paid_at = _parse_iso(ent.get("first_paid_at")) or row.first_paid_at
            row.last_paid_at = _parse_iso(ent.get("last_paid_at")) or row.last_paid_at
            row.last_out_trade_no = ent.get("last_out_trade_no")
            row.last_trade_no = ent.get("last_trade_no")
            upserted_ents += 1

        db.commit()

    print(f"upserted orders={upserted_orders} entitlements={upserted_ents}")
    if archive_json and store.is_file():
        bak = store.with_suffix(".json.bak")
        store.rename(bak)
        print(f"archived JSON -> {bak}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate FHD model_payment JSON to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument("--apply", action="store_true", help="执行 UPSERT")
    parser.add_argument("--archive-json", action="store_true", help="成功后把 JSON 改名为 .bak")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("请指定 --dry-run 或 --apply")
    return migrate(dry_run=args.dry_run, archive_json=args.archive_json)


if __name__ == "__main__":
    raise SystemExit(main())
