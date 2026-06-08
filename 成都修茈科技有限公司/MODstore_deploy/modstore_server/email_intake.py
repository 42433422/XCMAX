"""IMAP email intake bridge -> ``ops.intake.email`` events."""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
import os
import re
from email.message import Message
from email.utils import parseaddr
from typing import Any, Dict, List

from modstore_server.email_service import _load_modstore_env

logger = logging.getLogger(__name__)

_poll_fail_streak = 0


def poll_fail_streak() -> int:
    return _poll_fail_streak


def _imap_credentials() -> tuple[str, str]:
    user = (
        os.environ.get("MODSTORE_EMAIL_INTAKE_IMAP_USER")
        or os.environ.get("MODSTORE_IMAP_USER")
        or os.environ.get("MODSTORE_SMTP_USER")
        or ""
    ).strip()
    password = (
        os.environ.get("MODSTORE_EMAIL_INTAKE_IMAP_PASSWORD")
        or os.environ.get("MODSTORE_IMAP_PASSWORD")
        or os.environ.get("MODSTORE_SMTP_PASSWORD")
        or ""
    ).strip()
    return user, password


def _safe_header(msg: Message, name: str) -> str:
    """Return a header as a plain string, tolerating malformed values.

    Python 3.11's strict ``email.policy.default`` parser raises HeaderParseError
    (surfacing as IndexError) on non-RFC Message-IDs such as Microsoft's
    ``<[hash-base32=@microsoft.com]>`` form. Falls back to the raw header list
    so a single bad mail does not abort the whole poll batch.
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


def _decode_payload(part: Message) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html or "")
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _message_body_text(msg: Message) -> str:
    if msg.is_multipart():
        plain: List[str] = []
        html_fallback: List[str] = []
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                plain.append(_decode_payload(part))
            elif ctype == "text/html":
                html_fallback.append(_strip_html(_decode_payload(part)))
        if plain:
            return "\n".join([x for x in plain if x]).strip()
        return "\n".join([x for x in html_fallback if x]).strip()
    ctype = (msg.get_content_type() or "").lower()
    if ctype == "text/plain":
        return _decode_payload(msg).strip()
    if ctype == "text/html":
        return _strip_html(_decode_payload(msg))
    return ""


def _looks_like_approval_reply(from_addr: str, body: str) -> bool:
    auth = (os.environ.get("MODSTORE_APPROVAL_AUTHORIZED_FROM") or "").strip().lower()
    if not auth:
        return False
    if (from_addr or "").strip().lower() != auth:
        return False
    return bool(re.search(r"\b[A-F0-9]{6}\b", body or "", flags=re.IGNORECASE))


def _emit_email_event(
    *,
    from_addr: str,
    subject: str,
    body: str,
    message_id: str,
    date_hdr: str,
) -> bool:
    try:
        from modstore_server.incident_bus import publish
    except Exception:
        logger.exception("email intake: incident_bus import failed")
        return False

    source_ref = (
        message_id
        or hashlib.sha256(
            f"{from_addr}|{subject}|{date_hdr}|{body[:500]}".encode("utf-8")
        ).hexdigest()[:24]
    )
    payload = {
        "subject_id": source_ref[:128],
        "source_ref": source_ref[:256],
        "channel": "email",
        "from": from_addr[:320],
        "subject": subject[:500],
        "body": body[:12_000],
        "snippet": body[:500],
        "message_id": message_id[:512],
        "date": date_hdr[:128],
    }
    fp = hashlib.sha256(f"ops.intake.email|{source_ref}".encode("utf-8")).hexdigest()[:64]
    return bool(
        publish(
            "ops.intake.email",
            payload,
            source="email-intake",
            fingerprint=fp,
        )
    )


def poll_email_intake_once() -> Dict[str, Any]:
    """Poll unread emails and publish ``ops.intake.email`` events."""
    global _poll_fail_streak
    _load_modstore_env()

    raw_en = (os.environ.get("MODSTORE_EMAIL_INTAKE_ENABLED", "1") or "").strip().lower()
    if raw_en in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "processed": 0, "published": 0}

    host = (
        os.environ.get("MODSTORE_EMAIL_INTAKE_IMAP_HOST")
        or os.environ.get("MODSTORE_IMAP_HOST")
        or "imap.qq.com"
    ).strip()
    try:
        port = int(
            os.environ.get("MODSTORE_EMAIL_INTAKE_IMAP_PORT")
            or os.environ.get("MODSTORE_IMAP_PORT")
            or "993"
        )
    except ValueError:
        port = 993
    search_query = (os.environ.get("MODSTORE_EMAIL_INTAKE_SEARCH") or "UNSEEN").strip() or "UNSEEN"
    try:
        max_messages = max(1, min(int(os.environ.get("MODSTORE_EMAIL_INTAKE_MAX", "20")), 200))
    except ValueError:
        max_messages = 20
    mark_seen = (
        os.environ.get("MODSTORE_EMAIL_INTAKE_MARK_SEEN", "1") or ""
    ).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    skip_approval_reply = (
        os.environ.get("MODSTORE_EMAIL_INTAKE_SKIP_APPROVAL_REPLY", "1") or ""
    ).strip().lower() not in ("0", "false", "no", "off")

    user, password = _imap_credentials()
    if not user or not password:
        return {"ok": False, "error": "missing credentials", "processed": 0, "published": 0}

    processed = 0
    published = 0
    skipped = 0
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")
        typ, data = mail.search(None, search_query)
        if typ != "OK" or not data or not data[0]:
            mail.logout()
            _poll_fail_streak = 0
            return {"ok": True, "processed": 0, "published": 0, "skipped": 0}

        ids = data[0].split()
        for raw_id in ids[:max_messages]:
            try:
                typ2, msg_data = mail.fetch(raw_id, "(RFC822)")
                if typ2 != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_msg = msg_data[0]
                blob = raw_msg[1] if isinstance(raw_msg, tuple) and len(raw_msg) >= 2 else raw_msg
                if not isinstance(blob, bytes):
                    continue
                processed += 1

                # 用 compat32 策略：headers 始终是普通字符串，避免 email.policy.default
                # 在解析非 RFC Message-ID（如某些 Microsoft 邮件的 <[hash=@microsoft.com]>）时抛 IndexError。
                msg = email.message_from_bytes(blob, policy=email.policy.compat32)
                from_addr = (parseaddr(_safe_header(msg, "From"))[1] or "").strip()
                subject = _safe_header(msg, "Subject")
                message_id = _safe_header(msg, "Message-ID")
                date_hdr = _safe_header(msg, "Date")
                try:
                    body = _message_body_text(msg)
                except Exception:
                    logger.exception("email intake: decode body failed mid=%s", message_id)
                    body = ""

                if skip_approval_reply and _looks_like_approval_reply(from_addr, body):
                    skipped += 1
                else:
                    try:
                        ok = _emit_email_event(
                            from_addr=from_addr,
                            subject=subject,
                            body=body,
                            message_id=message_id,
                            date_hdr=date_hdr,
                        )
                    except Exception:
                        logger.exception("email intake: emit event failed mid=%s", message_id)
                        ok = False
                    if ok:
                        published += 1
                    else:
                        skipped += 1
            except Exception:
                logger.exception("email intake: skip malformed mail id=%s", raw_id)
                skipped += 1
            finally:
                # 即使解析失败也标记为已读，避免同一封异常邮件持续拉低失败计数。
                if mark_seen:
                    try:
                        mail.store(raw_id, "+FLAGS", "\\Seen")
                    except Exception:
                        logger.debug("email intake: mark seen failed", exc_info=True)
        mail.logout()
        _poll_fail_streak = 0
        return {
            "ok": True,
            "processed": processed,
            "published": published,
            "skipped": skipped,
            "search_query": search_query,
        }
    except Exception as exc:
        _poll_fail_streak += 1
        logger.exception("email intake poll failed")
        return {
            "ok": False,
            "error": str(exc)[:300],
            "processed": processed,
            "published": published,
            "skipped": skipped,
            "fail_streak": _poll_fail_streak,
        }


__all__ = ["poll_email_intake_once", "poll_fail_streak"]
