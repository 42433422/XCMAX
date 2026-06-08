"""IMAP 收件：拉取未读邮件，匹配审批 token 并触发 approval_dispatcher。

凭证与 SMTP 发信相同：默认使用 ``MODSTORE_SMTP_USER`` / ``MODSTORE_SMTP_PASSWORD``（QQ 邮箱授权码）。
需在 QQ 邮箱设置中单独开启「IMAP/SMTP」中的 IMAP 服务。
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import os
import re
from email.message import Message
from email.utils import parseaddr
from typing import Any, Dict, List

from modstore_server.approval_dispatcher import handle_incoming_approval_email
from modstore_server.email_service import _load_modstore_env

logger = logging.getLogger(__name__)


def _imap_credentials() -> tuple[str, str]:
    """登录邮箱：默认与发信 SMTP 完全一致（QQ 同一账号 + 授权码）。

    仅当需要与 SMTP 使用不同账号时再设 ``MODSTORE_IMAP_USER`` / ``MODSTORE_IMAP_PASSWORD``。
    """
    user = (
        os.environ.get("MODSTORE_IMAP_USER") or os.environ.get("MODSTORE_SMTP_USER") or ""
    ).strip()
    password = (
        os.environ.get("MODSTORE_IMAP_PASSWORD") or os.environ.get("MODSTORE_SMTP_PASSWORD") or ""
    ).strip()
    return user, password


_poll_fail_streak = 0


def poll_fail_streak() -> int:
    return _poll_fail_streak


def _decode_payload(part: Message) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:
        return ""


def _message_body_text(msg: Message) -> str:
    if msg.is_multipart():
        plain: List[str] = []
        html_fallback: List[str] = []
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain" and "attachment" not in (
                part.get("Content-Disposition") or ""
            ):
                plain.append(_decode_payload(part))
            elif ctype == "text/html" and "attachment" not in (
                part.get("Content-Disposition") or ""
            ):
                t = _decode_payload(part)
                s = re.sub(r"(?is)<script.*?>.*?</script>", "", t)
                s = re.sub(r"(?is)<style.*?>.*?</style>", "", s)
                s = re.sub(r"<[^>]+>", " ", s)
                html_fallback.append(s)
        if plain:
            return "\n".join(plain)
        if html_fallback:
            return "\n".join(html_fallback)
        return ""
    ctype = (msg.get_content_type() or "").lower()
    if ctype == "text/plain":
        return _decode_payload(msg)
    if ctype == "text/html":
        t = _decode_payload(msg)
        t = re.sub(r"(?is)<script.*?>.*?</script>", "", t)
        t = re.sub(r"(?is)<style.*?>.*?</style>", "", t)
        t = re.sub(r"<[^>]+>", " ", t)
        return t
    return ""


def _safe_header(msg: Message, name: str) -> str:
    """Return header as plain string, tolerating malformed values.

    Python 3.11's ``email.policy.default`` strict parser raises HeaderParseError
    (and IndexError downstream) on non-RFC Message-IDs such as Microsoft's
    ``<[hash-base32=@microsoft.com]>`` form. We fall back to the raw header
    list so a single bad mail does not abort the whole poll batch.
    """
    try:
        v = msg.get(name)
        if v is None:
            return ""
        return str(v).strip()
    except Exception:
        try:
            raw_headers = getattr(msg, "_headers", None) or []
            for k, v in raw_headers:
                if isinstance(k, str) and k.lower() == name.lower():
                    return str(v).strip() if v is not None else ""
        except Exception:
            pass
        return ""


def poll_inbox_once() -> Dict[str, Any]:
    """处理 INBOX 中未读邮件（最多 20 封）。成功返回 processed 计数。"""
    global _poll_fail_streak
    _load_modstore_env()

    raw_en = os.environ.get("MODSTORE_INBOX_POLL_ENABLED", "1").strip().lower()
    if raw_en in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "processed": 0}

    host = os.environ.get("MODSTORE_IMAP_HOST", "imap.qq.com").strip()
    try:
        port = int(os.environ.get("MODSTORE_IMAP_PORT", "993"))
    except ValueError:
        port = 993
    user, password = _imap_credentials()
    if not user or not password:
        logger.warning(
            "inbox poller: missing credentials — IMAP reuses SMTP; set MODSTORE_SMTP_USER and MODSTORE_SMTP_PASSWORD "
            "(optional override: MODSTORE_IMAP_USER / MODSTORE_IMAP_PASSWORD)"
        )
        return {"ok": False, "error": "missing credentials", "processed": 0}

    processed = 0
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")
        typ, data = mail.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            mail.logout()
            _poll_fail_streak = 0
            return {"ok": True, "processed": 0}

        ids = data[0].split()
        for raw_id in ids[:20]:
            try:
                num = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                typ2, msg_data = mail.fetch(num, "(RFC822)")
                if typ2 != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_msg = msg_data[0]
                if isinstance(raw_msg, tuple) and len(raw_msg) >= 2:
                    blob = raw_msg[1]
                else:
                    blob = raw_msg
                if not isinstance(blob, bytes):
                    continue
                # 用 compat32 策略：headers 始终是普通字符串，不会因为非 RFC Message-ID
                # 触发 email._header_value_parser 的严格解析失败（IndexError）。
                msg = email.message_from_bytes(blob, policy=email.policy.compat32)
                from_addr = (parseaddr(_safe_header(msg, "From"))[1] or "").strip()
                mid = _safe_header(msg, "Message-ID")
                try:
                    body = _message_body_text(msg)
                except Exception:
                    logger.exception("decode body failed mid=%s", mid)
                    body = ""
                try:
                    res = handle_incoming_approval_email(
                        from_addr=from_addr, body=body, message_id=mid
                    )
                    if res.get("ok") or not res.get("skip"):
                        processed += 1
                except Exception:
                    logger.exception("handle incoming approval failed mid=%s", mid)
            except Exception:
                logger.exception("inbox poller: skip malformed mail id=%s", raw_id)
            finally:
                # 无论解析是否成功，都标记为已读，避免同一封异常邮件持续触发失败计数。
                try:
                    mail.store(raw_id, "+FLAGS", "\\Seen")
                except Exception:
                    logger.exception("mark seen failed id=%s", raw_id)

        mail.logout()
        _poll_fail_streak = 0
        return {"ok": True, "processed": processed}
    except Exception as e:  # noqa: BLE001
        _poll_fail_streak += 1
        logger.exception("IMAP poll failed: %s", e)
        return {
            "ok": False,
            "error": str(e),
            "processed": processed,
            "fail_streak": _poll_fail_streak,
        }
