"""桌面 QR 配对短期 nonce 存储（进程内 + 可选文件）。

v2: 新增 6 位数字配对码(shortCode)支持，QR 可携带 host/port 作为首次绑定直连兜底。
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

_lock = threading.Lock()
_nonces: dict[str, dict[str, Any]] = {}
# shortCode(6位数字) -> nonce 的反向索引，用于手机输入配对码查询
_short_codes: dict[str, str] = {}

# 6 位人工输入码只有约 20 bit 熵，匿名 lookup/exchange 必须有失败锁定。
# 限制同时按源 IP 和（如有）设备 ID 计算；命中任一维度都拒绝。
PAIRING_FAILURE_LIMIT = 5
PAIRING_FAILURE_WINDOW_SECONDS = 60
PAIRING_FAILURE_LOCK_SECONDS = 120
_pairing_failures: dict[str, dict[str, Any]] = {}


def pairing_failure_retry_after(keys: list[str]) -> int:
    """返回来源当前锁定剩余秒数；0 表示可继续尝试。"""
    now = time.time()
    retry_after = 0
    clean_keys = {str(key).strip() for key in keys if str(key).strip()}
    with _lock:
        for key in clean_keys:
            state = _pairing_failures.get(key)
            if not state:
                continue
            locked_until = float(state.get("locked_until") or 0)
            if locked_until > now:
                retry_after = max(retry_after, int(locked_until - now) + 1)
                continue
            attempts = [
                float(ts)
                for ts in state.get("attempts", [])
                if now - float(ts) < PAIRING_FAILURE_WINDOW_SECONDS
            ]
            if attempts:
                state["attempts"] = attempts
                state["locked_until"] = 0.0
            else:
                _pairing_failures.pop(key, None)
    return retry_after


def record_pairing_failure(keys: list[str]) -> int:
    """记录一次无效猜测；达到阈值时立即锁定并返回等待秒数。"""
    now = time.time()
    retry_after = 0
    clean_keys = {str(key).strip() for key in keys if str(key).strip()}
    with _lock:
        for key in clean_keys:
            state = _pairing_failures.setdefault(key, {"attempts": [], "locked_until": 0.0})
            locked_until = float(state.get("locked_until") or 0)
            if locked_until > now:
                retry_after = max(retry_after, int(locked_until - now) + 1)
                continue
            attempts = [
                float(ts)
                for ts in state.get("attempts", [])
                if now - float(ts) < PAIRING_FAILURE_WINDOW_SECONDS
            ]
            attempts.append(now)
            state["attempts"] = attempts
            if len(attempts) >= PAIRING_FAILURE_LIMIT:
                state["locked_until"] = now + PAIRING_FAILURE_LOCK_SECONDS
                retry_after = max(retry_after, PAIRING_FAILURE_LOCK_SECONDS)
    return retry_after


def clear_pairing_failures(keys: list[str]) -> None:
    """合法配对成功后清除该来源的失败计数。"""
    clean_keys = {str(key).strip() for key in keys if str(key).strip()}
    with _lock:
        for key in clean_keys:
            _pairing_failures.pop(key, None)


def reset_pairing_failure_limits() -> None:
    """清空进程内失败锁定（测试与受控运维使用）。"""
    with _lock:
        _pairing_failures.clear()


def _gen_short_code() -> str:
    """生成 6 位数字配对码（100000-999999），避免碰撞。"""
    for _ in range(100):
        code = str(secrets.randbelow(900_000) + 100_000)
        if code not in _short_codes:
            return code
    # 极低概率：随机数池快耗尽时回退到 token 截取
    return str(secrets.randbelow(900_000) + 100_000)


def issue_pairing_nonce(
    host: str,
    port: int,
    ttl_seconds: int = 120,
    *,
    issuer_user_id: int,
    subject_user_id: int,
    subject_username: str,
    tenant_id: int | None,
    company_brand: str,
) -> dict[str, Any]:
    """签发绑定管理端身份的短期、一次性配对载荷。

    ``subject_user_id`` 当前等于签发管理员，但交换后只会获得
    ``enterprise_pairing`` 受限凭证；签发身份与租户在 nonce 创建时固定，
    不能由手机交换请求覆盖。
    """
    issuer_uid = int(issuer_user_id or 0)
    subject_uid = int(subject_user_id or 0)
    if issuer_uid <= 0 or subject_uid <= 0:
        raise ValueError("配对签发必须绑定有效管理用户")
    # ``0`` is the explicit local/single-tenant namespace.  Keeping it in the
    # signed credential is safer than an absent tenant claim that downstream
    # code could accidentally interpret as unrestricted.
    clean_tenant_id = int(tenant_id) if tenant_id is not None else 0
    ttl = max(30, min(int(ttl_seconds or 120), 300))
    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + ttl
    short_code = _gen_short_code()
    payload = {
        "host": host,
        "port": port,
        "nonce": nonce,
        "shortCode": short_code,
        "exp": exp,
        "issuer_user_id": issuer_uid,
        "subject_user_id": subject_uid,
        "subject_username": str(subject_username or "").strip()[:128],
        "tenant_id": clean_tenant_id,
        "company_brand": str(company_brand or "").strip()[:256],
        "account_kind": "enterprise",
        "token_scope": "enterprise_pairing",
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


def lookup_pairing_nonce(nonce: str) -> dict[str, Any] | None:
    """读取未过期 nonce 的副本，不消费；用于交换前做租户约束检查。"""
    clean = str(nonce or "").strip()
    if not clean:
        return None
    with _lock:
        rec = _nonces.get(clean)
        if not rec or int(rec.get("exp") or 0) < int(time.time()):
            return None
        return dict(rec)


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
