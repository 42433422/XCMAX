"""本地一键启动：先加载 ``MODstore_deploy/.env``，必要时从 ``keys/*.pem`` 注入密钥。

正式支付：``ALIPAY_DEBUG=0``，``ALIPAY_APP_ID``、应用私钥、支付宝公钥须与
https://open.alipay.com 中「正式应用」一致；``ALIPAY_NOTIFY_URL`` 须为公网 HTTPS（可回调），勿用 127.0.0.1。
沙箱联调：沙箱 APPID + ``ALIPAY_DEBUG=1``，未设回调时可默认同机 http://127.0.0.1:… 仅作本地调试用。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _alipay_sandbox_mode() -> bool:
    v = (os.environ.get("ALIPAY_DEBUG") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")

_root = Path(__file__).resolve().parent
try:
    os.chdir(_root)
except OSError:
    pass

def _load_dotenv_merge(path: Path) -> None:
    """覆盖同名键，但文件中的空值不抹掉已在 .env 里加载的非空变量（避免 .env.local 留空 ALIPAY_APP_ID= 盖掉 .env）。"""
    if not path.is_file():
        return
    try:
        from dotenv import dotenv_values
    except ImportError:
        from dotenv import load_dotenv

        load_dotenv(path, override=True)
        return
    for key, val in dotenv_values(path).items():
        if val is None:
            continue
        if not (val or "").strip() and (os.environ.get(key) or "").strip():
            continue
        os.environ[key] = val


try:
    from dotenv import load_dotenv

    load_dotenv(_root / ".env", override=False)
    _load_dotenv_merge(_root / ".env.local")
except ImportError:
    pass


def _maybe_fill_keys_from_files() -> None:
    if os.environ.get("ALIPAY_APP_PRIVATE_KEY") or os.environ.get("ALIPAY_APP_PRIVATE_KEY_PATH"):
        return
    priv = _root / "keys" / "app_private_key.pem"
    if priv.is_file():
        os.environ["ALIPAY_APP_PRIVATE_KEY"] = priv.read_text(encoding="utf-8")
    pub = _root / "keys" / "alipay_public_key.pem"
    if not os.environ.get("ALIPAY_ALIPAY_PUBLIC_KEY") and not os.environ.get("ALIPAY_ALIPAY_PUBLIC_KEY_PATH"):
        if pub.is_file():
            os.environ["ALIPAY_ALIPAY_PUBLIC_KEY"] = pub.read_text(encoding="utf-8")


_maybe_fill_keys_from_files()

_app_id = (os.environ.get("ALIPAY_APP_ID") or os.environ.get("ALIPAY_PID") or "").strip()
if not _app_id:
    print(
        "未配置 ALIPAY_APP_ID。请在 MODstore_deploy/.env 中填写支付宝「应用 APPID」："
        "正式环境见 https://open.alipay.com 控制台；沙箱见 https://open.alipay.com/develop/sandbox/app 。"
        "须与 ALIPAY_DEBUG 一致（正式 ALIPAY_DEBUG=0，沙箱 ALIPAY_DEBUG=1），并配置匹配的应用私钥与支付宝公钥。",
        file=sys.stderr,
    )
    sys.exit(1)

if not (os.environ.get("ALIPAY_DEBUG") or "").strip():
    os.environ["ALIPAY_DEBUG"] = "0"

_notify = (os.environ.get("ALIPAY_NOTIFY_URL") or "").strip()
if not _notify:
    if _alipay_sandbox_mode():
        os.environ["ALIPAY_NOTIFY_URL"] = (
            "http://127.0.0.1:8765/api/payment/notify/alipay"
        )
    else:
        print(
            "正式收款须设置公网可访问的 ALIPAY_NOTIFY_URL（HTTPS，与线上一致），"
            "例如 https://你的域名/api/payment/notify/alipay；"
            "勿使用 127.0.0.1。在服务器 .env 或 systemd Environment= 中配置后重启。",
            file=sys.stderr,
        )
        sys.exit(1)
elif not _alipay_sandbox_mode():
    nlow = _notify.lower()
    if "127.0.0.1" in _notify or "localhost" in nlow:
        print(
            "ALIPAY_DEBUG=0 时 ALIPAY_NOTIFY_URL 不能为 127.0.0.1 或 localhost；"
            "请改为支付宝能访问的公网 HTTPS 地址。",
            file=sys.stderr,
        )
        sys.exit(1)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("modstore_server.app:app", host="127.0.0.1", port=8765, reload=False)
