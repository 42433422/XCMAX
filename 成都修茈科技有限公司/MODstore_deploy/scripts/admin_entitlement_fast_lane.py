#!/usr/bin/env python3
"""Terminal shortcut for the audited entitlement fast lane.

Examples:
  ./scripts/admin_entitlement_fast_lane.py plans
  ./scripts/admin_entitlement_fast_lane.py status SUNBIRD
  ./scripts/admin_entitlement_fast_lane.py grant SUNBIRD saas-permanent-growth \
    --actor founder --reason '创始人确认永久成长版'
  ./scripts/admin_entitlement_fast_lane.py revoke SUNBIRD saas-permanent-growth \
    --actor founder --reason '客户确认撤销授权'
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modstore_server.entitlement_fast_lane import (  # noqa: E402
    FastLaneError,
    account_fast_lane_status,
    apply_fast_lane_action,
    list_fast_lane_plans,
)
from modstore_server.models import get_session_factory, init_db  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="管理员套餐/权益快速通道（不生成订单或支付）"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plans", help="列出所有可绑定套餐")
    status = sub.add_parser("status", help="查询账号当前权益")
    status.add_argument("account", help="用户 ID、用户名或邮箱")

    for command in ("grant", "assign", "revoke"):
        action = sub.add_parser(command, help=f"{command} 指定套餐")
        action.add_argument("account", help="用户 ID、用户名或邮箱")
        action.add_argument("plan_id", help="plan_templates.plan_id")
        action.add_argument("--actor", required=True, help="操作管理员 ID、用户名或邮箱")
        action.add_argument("--reason", required=True, help="审计原因，至少 4 个字")
        action.add_argument("--days", type=int, default=None, help="会员权益有效天数")
        action.add_argument(
            "--idempotency-key",
            default="",
            help="重试时复用同一键；留空则自动生成",
        )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable | None = None,
) -> dict:
    args = build_parser().parse_args(argv)
    if session_factory is None:
        init_db()
        session_factory = get_session_factory()
    with session_factory() as db:
        if args.command == "plans":
            return {
                "items": list_fast_lane_plans(db),
                "commerce": {
                    "order_generated": False,
                    "payment_generated": False,
                    "transaction_generated": False,
                },
            }
        if args.command == "status":
            return account_fast_lane_status(db, args.account)
        action = "assign" if args.command in {"grant", "assign"} else "revoke"
        key = args.idempotency_key.strip() or (
            f"fast-lane-cli-{action}-{uuid.uuid4().hex}"
        )
        return apply_fast_lane_action(
            db,
            actor=args.actor,
            account=args.account,
            action=action,
            plan_id=args.plan_id,
            reason=args.reason,
            idempotency_key=key,
            duration_days=args.days,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except FastLaneError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
