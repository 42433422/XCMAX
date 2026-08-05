#!/usr/bin/env python3
"""模拟 MODstore 支付成功回调，向 FHD 投递一个 `payment.paid` webhook。

用于验证「MODstore 支付成功 → FHD webhook → NeuroBus + 回款核销」闭环。
不依赖 MODstore 服务运行，直接按 `PAYMENT_CONTRACT.md` §4 envelope 契约构造并签名投递，
签名算法与生产 `modstore_server.webhook_dispatcher._signature` 完全一致。

示例::

    python scripts/simulate_paid_webhook.py \\
        --url http://127.0.0.1:8000/api/xcmax/webhooks/modstore/payment \\
        --secret <FHD 的 MODSTORE_ORDER_WEBHOOK_SECRET> \\
        --user-id 42 --amount 99.00 --subject 企业版月费

参数说明：
    --url       FHD webhook 端点（默认本机 8000）。
    --secret    若 FHD 配置了 MODSTORE_ORDER_WEBHOOK_SECRET，则必须传相同值；
                为空时 FHD 侧跳过验签。脚本仅在传入 secret 时附加签名头。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request


def hmac_signature(secret: str, timestamp: str, event_id: str, body: bytes) -> str:
    """与 `modstore_server.webhook_dispatcher._signature` 保持一致：
    HMAC-SHA256(secret, "{timestamp}.{event_id}.{body}")。"""
    msg = timestamp.encode("utf-8") + b"." + event_id.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def build_paid_event(
    *,
    out_trade_no: str,
    user_id: int,
    subject: str,
    total_amount: str,
    order_kind: str = "",
) -> dict:
    """构造 PAYMENT_CONTRACT.md §4 的 `payment.paid` envelope。"""
    event_id = f"payment.paid:{out_trade_no}"
    return {
        "id": event_id,
        "type": "payment.paid",
        "version": 1,
        "source": "modstore-python",
        "aggregate_id": out_trade_no,
        "created_at": int(time.time()),
        "data": {
            "out_trade_no": out_trade_no,
            "user_id": user_id,
            "subject": subject,
            "total_amount": total_amount,
            "order_kind": order_kind,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="模拟 MODstore 支付成功回调，投递 payment.paid 到 FHD webhook"
    )
    p.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/xcmax/webhooks/modstore/payment",
        help="FHD webhook 端点",
    )
    p.add_argument(
        "--secret",
        default="",
        help="FHD 侧 MODSTORE_ORDER_WEBHOOK_SECRET；为空则 FHD 跳过验签",
    )
    p.add_argument(
        "--out-trade-no",
        default=f"MODSIM{int(time.time())}",
        help="商户订单号（决定幂等键 payment.paid:<out_trade_no>）",
    )
    p.add_argument("--user-id", type=int, required=True, help="market_user_id")
    p.add_argument("--amount", default="99.00", help="实付金额（元）")
    p.add_argument("--subject", default="企业版月费")
    p.add_argument("--order-kind", default="plan")
    args = p.parse_args()

    event = build_paid_event(
        out_trade_no=args.out_trade_no,
        user_id=args.user_id,
        subject=args.subject,
        total_amount=args.amount,
        order_kind=args.order_kind,
    )
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    event_id = event["id"]
    headers = {
        "Content-Type": "application/json",
        "X-Modstore-Webhook-Id": event_id,
        "X-Modstore-Webhook-Event": event["type"],
        "X-Modstore-Webhook-Timestamp": timestamp,
    }
    if args.secret:
        headers["X-Modstore-Webhook-Signature"] = (
            f"sha256={hmac_signature(args.secret, timestamp, event_id, body)}"
        )

    print(f"POST {args.url}")
    print(json.dumps(event, ensure_ascii=False, indent=2))
    req = urllib.request.Request(
        args.url, data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            print(f"\nHTTP {resp.status}")
            print(resp.read().decode("utf-8", errors="replace"))
            return 0 if resp.status < 400 else 1
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code}")
        print(exc.read().decode("utf-8", errors="replace"))
        return 1
    except urllib.error.URLError as exc:
        print(f"\n连接失败: {exc.reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())