#!/usr/bin/env python3
"""创建 Mod 试点企业沙箱商家（非 admin）并同步 FHD 本地账号。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
MODSTORE_DEPLOY = Path(
    os.environ.get(
        "MODSTORE_DEPLOY_ROOT",
        Path.home()
        / "XCMAX-archives/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy",
    )
)
MERCHANT_USER = os.environ.get("MOD_PILOT_MERCHANT_USER", "modpilot")
MERCHANT_PASS = os.environ.get("MOD_PILOT_MERCHANT_PASSWORD", "ModPilot2026!")
ADMIN_USER = os.environ.get("MOD_PILOT_ADMIN_USER", "testuser")
ADMIN_PASS = os.environ.get("MOD_PILOT_ADMIN_PASSWORD", "ModPilot2026!")
MODSTORE_PORT = os.environ.get("MODSTORE_PORT", "8788")
FHD_API = os.environ.get("MOD_PILOT_FHD_API", "http://127.0.0.1:5000")
BASE = f"http://127.0.0.1:{MODSTORE_PORT}"


def log(msg: str) -> None:
    print(f"[mod-pilot-merchant] {msg}", flush=True)


def grant_merchant() -> None:
    py = FHD_ROOT / ".venv/bin/python"
    if not py.is_file():
        py = Path(sys.executable)
    subprocess.run(
        [
            str(py),
            "-m",
            "scripts.grant_admin",
            "--username",
            MERCHANT_USER,
            "--password",
            MERCHANT_PASS,
            "--email",
            f"{MERCHANT_USER}@pilot.local",
            "--no-admin",
            "--reset-password",
        ],
        cwd=MODSTORE_DEPLOY,
        check=True,
    )
    sys.path.insert(0, str(MODSTORE_DEPLOY))
    from modstore_server.models import User, get_session_factory, init_db

    init_db()
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(User.username == MERCHANT_USER).first()
        if not user:
            raise SystemExit(f"商家账号未创建: {MERCHANT_USER}")
        user.is_enterprise = True
        user.is_admin = False
        session.commit()
    log(f"企业商家就绪: {MERCHANT_USER} (is_enterprise=True, is_admin=False)")


def grant_admin() -> None:
    py = FHD_ROOT / ".venv/bin/python"
    if not py.is_file():
        py = Path(sys.executable)
    subprocess.run(
        [
            str(py),
            "-m",
            "scripts.grant_admin",
            "--username",
            ADMIN_USER,
            "--password",
            ADMIN_PASS,
            "--email",
            "mod-pilot-admin@localhost",
            "--reset-password",
        ],
        cwd=MODSTORE_DEPLOY,
        check=True,
    )
    log(f"管理账号就绪: {ADMIN_USER}")


def sync_fhd_local_user() -> None:
    body = json.dumps(
        {
            "username": MERCHANT_USER,
            "password": MERCHANT_PASS,
            "account_kind": "enterprise",
        }
    ).encode()
    req = urllib.request.Request(
        f"{FHD_API}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"FHD 企业登录失败 ({exc.code}): {detail}") from exc
    if not data.get("success"):
        raise SystemExit(f"FHD 企业登录失败: {data.get('message') or data}")
    log(f"FHD 本地账号已 JIT 同步: {MERCHANT_USER}")


def main() -> int:
    if not MODSTORE_DEPLOY.is_dir():
        raise SystemExit(f"MODstore_deploy 不存在: {MODSTORE_DEPLOY}")
    grant_admin()
    grant_merchant()
    sync_fhd_local_user()
    log("商家沙箱租户 setup 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
