#!/usr/bin/env python3
"""校验 surface_audit 演示企业号能否在修茈市场登录。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
CFG = FHD_ROOT / "config" / "surface_audit_demo_account.json"


def main() -> int:
    market = (os.environ.get("XCAGI_MARKET_BASE_URL") or "https://xiu-ci.com").strip().rstrip("/")
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    user = str(cfg.get("username") or "").strip()
    password = str(cfg.get("password") or "")
    official = str(cfg.get("market_base_url_official") or "").strip().rstrip("/")
    if not user or not password:
        print(f"[ERR] 无法读取 {CFG}", file=sys.stderr)
        return 1

    print(f"[verify] 市场 {market}")
    print(f"[verify] 账号 {user}")
    if official and market != official:
        print(f"[hint] 官网已注册：{official} · 本地开发可 XCAGI_USE_REMOTE_MARKET=1")

    body = json.dumps({"username": user, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{market}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
        print("[ERR] 市场登录失败", file=sys.stderr)
        print("  message:", raw.get("message") or raw.get("detail"), file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"[ERR] 无法连接市场 {market}: {exc.reason}", file=sys.stderr)
        return 1

    ok = bool(raw.get("ok") or raw.get("success"))
    user_blob = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    print("[OK] 市场登录成功" if ok else "[ERR] 市场登录失败")
    print("  is_enterprise:", user_blob.get("is_enterprise"))
    print("  is_admin:", user_blob.get("is_admin"))
    print("  user_id:", user_blob.get("id"))
    if not ok:
        print("  message:", raw.get("message") or raw.get("detail"))
        return 1
    if user_blob.get("is_admin"):
        print("[ERR] 演示号不应为管理员", file=sys.stderr)
        return 1
    if user_blob.get("is_enterprise") is not True:
        print("[WARN] 市场未标记 is_enterprise=true，企业入口可能拒绝")
    print(f"[OK] 演示号可在 {market} 用于企业账号登录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
