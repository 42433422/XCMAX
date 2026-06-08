#!/usr/bin/env python3
"""CLI: list or discard rows in ``event_outbox_dlq``."""

from __future__ import annotations

import argparse
import os


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list DLQ rows")
    ls.add_argument("--limit", type=int, default=50)
    disc = sub.add_parser("discard", help="delete one DLQ row by id")
    disc.add_argument("row_id", type=int)
    args = p.parse_args()

    from modstore_server.models import OutboxDeadLetter, get_session_factory

    sf = get_session_factory()
    with sf() as db:
        if args.cmd == "list":
            rows = (
                db.query(OutboxDeadLetter).order_by(OutboxDeadLetter.id.desc()).limit(max(1, args.limit)).all()
            )
            for r in rows:
                print(r.id, r.event_id, r.event_name, (r.last_error or "")[:120])
        else:
            row = db.query(OutboxDeadLetter).filter(OutboxDeadLetter.id == args.row_id).first()
            if not row:
                print("not found")
                return 1
            db.delete(row)
            db.commit()
            print("discarded", args.row_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
