#!/usr/bin/env python3
"""校验 Mod 试点支付宝沙箱：APPID ↔ keys 是否匹配（避免 invalid-signature）。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODSTORE_DEPLOY = Path(
    os.environ.get(
        "MODSTORE_DEPLOY_ROOT",
        Path.home()
        / "XCMAX-archives/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy",
    )
)
PORT = os.environ.get("MODSTORE_PORT", "8788")
BASE = f"http://127.0.0.1:{PORT}"
USER = os.environ.get("MOD_PILOT_MERCHANT_USER", "modpilot")
PASSWORD = os.environ.get("MOD_PILOT_MERCHANT_PASSWORD", "ModPilot2026!")


def main() -> int:
    sys.path.insert(0, str(MODSTORE_DEPLOY))
    from modstore_server import alipay_service

    snap = alipay_service.diagnostics_snapshot()
    print("[verify-alipay] diagnostics:", json.dumps(snap, ensure_ascii=False))
    if not snap.get("alipay_configured"):
        print("[verify-alipay] FAIL: alipay 未配置（检查 ALIPAY_* 环境变量与 app_factory 保留逻辑）", file=sys.stderr)
        return 1

    login = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                f"{BASE}/api/auth/login",
                data=json.dumps({"username": USER, "password": PASSWORD}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=30,
        ).read()
    )
    token = login.get("access_token") or login.get("token")
    if not token:
        print(f"[verify-alipay] FAIL: 无法登录 {USER}", file=sys.stderr)
        return 1

    sign = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                f"{BASE}/api/payment/sign-checkout",
                data=json.dumps(
                    {
                        "plan_id": "",
                        "item_id": 0,
                        "total_amount": 0.01,
                        "subject": "verify-alipay",
                        "wallet_recharge": True,
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            ),
            timeout=30,
        ).read()
    )
    body = {
        "plan_id": sign.get("plan_id") or "",
        "item_id": sign.get("item_id") or 0,
        "total_amount": sign.get("total_amount") or 0.01,
        "subject": sign.get("subject") or "verify-alipay",
        "wallet_recharge": True,
        "request_id": sign["request_id"],
        "timestamp": sign["timestamp"],
        "signature": sign["signature"],
    }
    req = urllib.request.Request(
        f"{BASE}/api/payment/checkout",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        checkout = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as exc:
        print(f"[verify-alipay] FAIL: checkout HTTP {exc.code} {exc.read()[:300]}", file=sys.stderr)
        return 1

    redirect = str(checkout.get("redirect_url") or "")
    if not redirect:
        print(f"[verify-alipay] FAIL: checkout 无 redirect_url: {checkout}", file=sys.stderr)
        return 1

    page = urllib.request.urlopen(redirect, timeout=60).read().decode("utf-8", errors="replace")
    if "invalid-signature" in page or "验签出错" in page:
        print(
            "[verify-alipay] FAIL: 支付宝沙箱 invalid-signature — APPID 与 keys/ 不匹配。\n"
            "  → 打开 https://open.alipay.com/develop/sandbox/app\n"
            "  → 复制沙箱 APPID，下载/粘贴配套应用私钥与支付宝公钥到 MODstore_deploy/keys/\n"
            "  → 更新 .env ALIPAY_APP_ID=… 并重启 MODstore :8788",
            file=sys.stderr,
        )
        return 2
    if "登录" in page or "alipay" in page.lower():
        print("[verify-alipay] OK: 沙箱网关接受签名（可继续 0.01 元付款）")
        return 0
    print("[verify-alipay] WARN: 未识别页面内容，请人工打开 redirect_url 确认")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
