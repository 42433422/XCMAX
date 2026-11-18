#!/usr/bin/env python3
"""Publish one proactive event from a watcher, cron job or Rundeck step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application.proactive.service import (  # noqa: E402
    ProactiveEvent,
    ProactiveService,
    apprise_sender,
    in_app_sender,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="发布一条主动提醒事件")
    parser.add_argument("--kind", required=True, help="事件类型，如 inventory_low")
    parser.add_argument("--title", required=True, help="提醒标题")
    parser.add_argument("--detail", default="", help="提醒正文")
    parser.add_argument("--fingerprint", default="", help="去重指纹，默认取类型+标题")
    parser.add_argument("--user-id", action="append", type=int, default=[], help="接收人，可重复")
    parser.add_argument("--no-apprise", action="store_true", help="只写站内 outbox，不外发")
    args = parser.parse_args()

    senders = [in_app_sender] if args.no_apprise else [in_app_sender, apprise_sender()]
    service = ProactiveService(senders=senders)
    result = service.publish(
        ProactiveEvent(
            kind=args.kind,
            title=args.title,
            detail=args.detail,
            fingerprint=args.fingerprint,
            user_ids=tuple(args.user_id),
        )
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
