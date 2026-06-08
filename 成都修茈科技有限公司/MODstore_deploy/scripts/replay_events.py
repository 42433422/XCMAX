#!/usr/bin/env python3
"""CLI: reset outbox rows to pending for dispatcher replay.

示例::

    python scripts/replay_events.py --event-name payment.paid --limit 20
"""

from __future__ import annotations

import argparse
import os


def main() -> int:
    p = argparse.ArgumentParser(description="Replay OutboxEvent rows (mark pending + drain once).")
    p.add_argument("--event-id", default="", help="Exact event_id to match")
    p.add_argument("--event-name", default="", help="Canonical event_name filter")
    p.add_argument("--since-id", type=int, default=0)
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    os.environ.setdefault("MODSTORE_DB_PATH", "")
    from modstore_server.models import OutboxEvent, get_session_factory
    from modstore_server.eventing.db_outbox import drain

    sf = get_session_factory()
    with sf() as db:
        q = db.query(OutboxEvent)
        if args.event_id:
            q = q.filter(OutboxEvent.event_id == args.event_id.strip())
        if args.event_name:
            q = q.filter(OutboxEvent.event_name == args.event_name.strip())
        if args.since_id > 0:
            q = q.filter(OutboxEvent.id >= args.since_id)
        rows = q.order_by(OutboxEvent.id.asc()).limit(max(1, min(args.limit, 500))).all()
        for row in rows:
            row.status = "pending"
            row.last_error = ""
        db.commit()
        print(f"reset {len(rows)} row(s) to pending")
    stats = drain(limit=max(1, min(args.limit, 200)))
    print("drain:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
