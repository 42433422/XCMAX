"""桌面 QR 配对短期 nonce 存储（进程内 + 可选文件）。

v2: 新增 6 位数字配对码(shortCode)支持，QR 中只暴露 token 不暴露 IP。
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from typing import Any

_lock = threading.Lock()
_nonces: dict[str, dict[str, Any]] = {}
# shortCode(6位数字) -> nonce 的反向索引，用于手机输入配对码查询
_short_codes: dict[str, str] = {}


def _gen_short_code() -> str:
    """生成 6 位数字配对码（100000-999999），避免碰撞。"""
    for _ in range(100):
        code = str(random.randint(100_000, 999_999))
        if code not in _short_codes:
            return code
    # 极低概率：随机数池快耗尽时回退到 token 截取
    return str(random.randint(100_000, 999_999))


def issue_pairing_nonce(host: str, port: int, ttl_seconds: int = 300) -> dict[str, Any]:
    """签发配对载荷，同时返回 nonce 和 shortCode。"""
    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + ttl_seconds
    short_code = _gen_short_code()
    payload = {
        "host": host,
        "port": port,
        "nonce": nonce,
        "shortCode": short_code,
        "exp": exp,
    }
    with _lock:
        _nonces[nonce] = payload
        _short_codes[short_code] = nonce
    return payload


def consume_pairing_nonce(nonce: str) -> dict[str, Any] | None:
    """消费 nonce（一次性），返回原始 payload 或 None。"""
    with _lock:
        rec = _nonces.pop(nonce, None)
    if not rec:
        return None
    if int(rec.get("exp") or 0) < int(time.time()):
        return None
    # 同时清理对应的 shortCode 索引
    sc = rec.get("shortCode", "")
    if sc:
        with _lock:
            _short_codes.pop(sc, None)
    return rec


def lookup_by_shortcode(code: str) -> dict[str, Any] | None:
    """通过 6 位配对码查询完整载荷（不消费，仅读取）。用于手机手动输入场景。"""
    if len(code.strip()) != 6 or not code.strip().isdigit():
        return None
    with _lock:
        nonce = _short_codes.get(code.strip())
    if not nonce:
        return None
    # 返回副本（含 host/port/nonce），让手机端拿到后去 exchange
    with _lock:
        rec = _nonces.get(nonce)
    if not rec or int(rec.get("exp") or 0) < int(time.time()):
        return None
    return dict(rec)


def consume_by_shortcode(code: str) -> dict[str, Any] | None:
    """通过 6 位配对码直接消费（= lookup + consume 合一）。"""
    rec = lookup_by_shortcode(code)
    if not rec:
        return None
    return consume_pairing_nonce(rec["nonce"])
