"""Pluggable SMS verification service.

The default ``debug`` provider stores verification codes server-side and returns
the code in API responses for local testing. Production deployments can replace
this module with Aliyun/Tencent providers without changing auth routes.
"""

from __future__ import annotations

import logging
import os
import random
import re

logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    phone = re.sub(r"\D+", "", raw or "")
    if phone.startswith("86") and len(phone) == 13:
        phone = phone[2:]
    return phone


def validate_phone(raw: str) -> str:
    phone = normalize_phone(raw)
    if not re.fullmatch(r"1[3-9]\d{9}", phone):
        raise ValueError("请填写有效手机号")
    return phone


def generate_sms_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_sms_code(phone: str, code: str, purpose: str) -> dict:
    provider = (os.environ.get("COSER_SMS_PROVIDER") or "debug").strip().lower()
    if provider == "debug":
        logger.warning("SMS debug code phone=%s purpose=%s code=%s", phone, purpose, code)
        return {"provider": "debug", "debug_code": code}
    # Provider adapters intentionally share this boundary.
    raise RuntimeError(f"短信 provider 尚未配置或未实现: {provider}")
