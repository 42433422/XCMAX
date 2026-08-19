# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def _new_unique_ops_token_plain(
    existing_hashes: set[str] | None = None,
    *,
    session: _facade().Any | None = None,
    attempts: int = 64,
) -> _facade().Tuple[str, str]:
    """Return a 6-hex token and sha256 hash that do not collide with stored tokens."""
    seen = existing_hashes if existing_hashes is not None else set()
    for _ in range(max(1, attempts)):
        plain = _facade().secrets.token_hex(3).upper()
        th = _facade().hashlib.sha256(plain.encode("utf-8")).hexdigest()
        if th in seen:
            continue
        if session is not None:
            exists = (
                session.query(_facade().OpsApprovalToken.id)
                .filter(_facade().OpsApprovalToken.token_hash == th)
                .first()
            )
            if exists:
                seen.add(th)
                continue
        seen.add(th)
        return (plain, th)
    raise RuntimeError("failed to generate a unique daily digest approval token")


def parse_daily_digest_recipient_emails(raw: str) -> _facade().List[str]:
    """解析 ``MODSTORE_DAILY_DIGEST_EMAIL``：逗号或分号分隔，去空白，校验含 ``@``。"""
    if not (raw or "").strip():
        return []
    out: _facade().List[str] = []
    for chunk in raw.replace(";", ",").split(","):
        e = chunk.strip()
        if e and "@" in e:
            out.append(e)
    return out


def _notify_daily_digest_in_app(subject: str, digest_delivered: bool) -> None:
    """摘要投递成功后，向配置的 ``MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS`` 发站内通知。"""
    if not digest_delivered:
        return
    raw = (_facade().os.environ.get("MODSTORE_DAILY_DIGEST_NOTIFY_USER_IDS") or "").strip()
    if not raw:
        return
    ids: _facade().List[int] = []
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            ids.append(int(p))
    if not ids:
        return
    try:
        from modstore_server.notification_service import NotificationType, create_notification

        body = f"MODstore 每日摘要邮件已投递：{subject}。也可在邮箱中查看全文。"
        for uid in ids:
            create_notification(
                user_id=uid,
                notification_type=NotificationType.SYSTEM,
                title="每日摘要已发送",
                content=body,
                data={"kind": "daily_digest", "subject": subject},
            )
        _facade().logger.info("daily digest in-app notifications sent user_ids=%s", ids)
    except Exception:
        _facade().logger.exception("daily digest in-app notify failed")


def _html_to_text_excerpt(body_html: str) -> str:
    """Make a readable full-text copy for search/list views while keeping the original HTML."""
    text = _facade().re.sub("(?is)<(script|style)\\b.*?</\\1>", " ", body_html or "")
    text = _facade().re.sub("(?s)<[^>]+>", " ", text)
    text = _facade().html.unescape(text)
    return _facade().re.sub("\\s+", " ", text).strip()


def count_on_duty_employees() -> int:
    """编制矩阵 duty_roster 内在岗岗位数（与 AdminDutyEmployeeGraph / yuangon 同源）。"""
    from modstore_server.duty_roster import all_planned_employee_ids

    return len(all_planned_employee_ids())


def autonomy_decisions_digest_html() -> str:
    """Render the last 24h autonomy/veto summary from the shared append-only store."""
    try:
        from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

        ensure_fhd_on_path()
        from app.domain.autonomy.audit_log import autonomy_daily_digest_html

        return autonomy_daily_digest_html(days=1)
    except Exception:
        _facade().logger.debug(
            "daily digest: FHD autonomy audit summary unavailable", exc_info=True
        )
        return ""


def count_catalog_employee_packs(session) -> int:
    """Catalog 库内 employee_pack 条目总数（含市场/工作流包，可大于编制数）。"""
    return int(
        session.query(_facade().func.count(_facade().CatalogItem.id))
        .filter(_facade().CatalogItem.artifact == "employee_pack")
        .scalar()
        or 0
    )
