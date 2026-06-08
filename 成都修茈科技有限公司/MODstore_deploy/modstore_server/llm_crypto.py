"""BYOK 字段加解密（Fernet），不落日志明文。"""

from __future__ import annotations

import os
import re
from typing import cast

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet | None:
    raw = (os.environ.get("MODSTORE_LLM_MASTER_KEY") or "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("ascii"))
    except Exception:
        return None


def fernet_configured() -> bool:
    return _fernet() is not None


def encrypt_secret(plain: str) -> str:
    f = _fernet()
    if not f:
        raise RuntimeError("MODSTORE_LLM_MASTER_KEY not configured")
    return cast(str, f.encrypt(plain.encode("utf-8")).decode("ascii"))


def decrypt_secret(token: str) -> str:
    f = _fernet()
    if not f:
        raise RuntimeError("MODSTORE_LLM_MASTER_KEY not configured")
    try:
        return cast(str, f.decrypt(token.encode("ascii")).decode("utf-8"))
    except InvalidToken as e:
        raise ValueError("invalid ciphertext") from e


def mask_api_key(key: str) -> str:
    s = (key or "").strip()
    if len(s) <= 8:
        return "****" if s else ""
    return s[:4] + "…" + s[-4:]


def mask_base_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    return re.sub(r"([?#].*)$", "", u)[:48] + ("…" if len(u) > 48 else "")
