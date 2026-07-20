"""T-E05 · 「客户不感知 AI/人」自动化验收（A3 + A4）。

实现 ``docs/roadmap/CUSTOMER_INVISIBLE_AI_ACCEPTANCE.md`` 中的：
- A3 · 账单条目不含「AI 代劳」字样
- A4 · 通知语言使用中性身份

测试策略：
1. **正向**：插入使用中性词（「客户经理」「专属助理」）的记录，扫描器应放行
2. **负向**：插入含敏感词（「AI 员工」「机器人代工」）的记录，扫描器应检出并报告
3. **边界**：空 title / None content / 大小写混合 / 繁体变体

扫描器实现：``_scan_forbidden_words`` 返回 ``(record_id, field, matched_word)`` 列表，
不在扫描器内部断言，让调用方（测试）决定如何处理违规。这样扫描器可在 CI 中
复用为生产期检查工具。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pytest


# --------------------------------------------------------------------------- #
# 敏感词字典（A3 + A4 共享）
# --------------------------------------------------------------------------- #

#: 账单与通知都不应出现的「AI 代劳」字样（大小写不敏感匹配）
FORBIDDEN_WORDS: tuple[str, ...] = (
    "AI 代劳",
    "AI 代",
    "AI 替代",
    "机器人代工",
    "机器人代",
    "自动回复",
    "无人值守",
    "AI 客服",
    "AI 员工",
    "AI 助理",
    "AI 自动处理",
    "AI 自动",
)

#: 中性身份词（A4 通知语言应优先使用）
NEUTRAL_IDENTITY_WORDS: tuple[str, ...] = (
    "客户经理",
    "专属助理",
    "您的服务团队",
    "服务团队",
)


# --------------------------------------------------------------------------- #
# 扫描器实现
# --------------------------------------------------------------------------- #


def _normalize(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def scan_text_for_forbidden_words(
    text: Any, *, forbidden: Iterable[str] = FORBIDDEN_WORDS
) -> list[str]:
    """扫描一段文本，返回所有命中的敏感词（大小写不敏感）。

    空文本返回 ``[]``；命中多个词时按出现顺序返回。
    """
    s = _normalize(text).lower()
    if not s:
        return []
    hits: list[str] = []
    for w in forbidden:
        if w.lower() in s:
            hits.append(w)
    return hits


def scan_records_for_forbidden_words(
    records: Iterable[dict[str, Any]],
    *,
    fields: tuple[str, ...],
    forbidden: Iterable[str] = FORBIDDEN_WORDS,
) -> list[dict[str, Any]]:
    """扫描多条记录的多个字段，返回违规清单。

    每条违规形如::

        {"record_id": ..., "field": "title", "value": "...", "hits": ["AI 员工"]}
    """
    violations: list[dict[str, Any]] = []
    for rec in records:
        rid = rec.get("id") or rec.get("record_id") or "<unknown>"
        for f in fields:
            value = rec.get(f)
            hits = scan_text_for_forbidden_words(value, forbidden=forbidden)
            if hits:
                violations.append(
                    {
                        "record_id": rid,
                        "field": f,
                        "value": _normalize(value),
                        "hits": hits,
                    }
                )
    return violations


# --------------------------------------------------------------------------- #
# DB isolation fixture（与 T-E01/T-E03 同模式）
# --------------------------------------------------------------------------- #


def _init_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "acceptance.sqlite"))
    monkeypatch.setenv("MODSTORE_PYTEST_USE_SQLITE", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))

    import modstore_server.db.base as _base
    import modstore_server.models as _models

    _base._engine = None
    _base._SessionFactory = None
    _models._engine = None
    _models._SessionFactory = None
    _models.init_db()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    _init_isolated_db(tmp_path, monkeypatch)
    from modstore_server.models import get_session_factory

    return {
        "sf": get_session_factory(),
        "orders_dir": tmp_path / "orders",
    }


def _make_user(sf, user_id: int = 3001) -> None:
    from modstore_server.models import User

    with sf() as session:
        if session.query(User).filter(User.id == user_id).first() is None:
            session.add(
                User(
                    id=user_id,
                    username=f"acceptance_user_{user_id}",
                    password_hash="x",
                )
            )
            session.commit()


# --------------------------------------------------------------------------- #
# A3 · 账单条目不含「AI 代劳」字样
# --------------------------------------------------------------------------- #


class TestAcceptanceA3BillWording:
    """A3 · 账单条目 ``Invoice.title`` / 订单 ``subject`` / ``Transaction.description``
    不应出现 FORBIDDEN_WORDS 中的任意一项。"""

    def test_clean_invoice_title_passes_scanner(self):
        records = [
            {"id": 1, "title": "客户经理代开增值税普通发票", "subject": "VIP 套餐"},
            {"id": 2, "title": "专属助理服务费", "subject": "钱包充值"},
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "subject")
        )
        assert violations == []

    def test_invoice_title_with_ai_employee_is_flagged(self):
        records = [
            {"id": 1, "title": "AI 员工 #1234 服务费", "subject": "VIP 套餐"},
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "subject")
        )
        assert len(violations) == 1
        assert violations[0]["record_id"] == 1
        assert violations[0]["field"] == "title"
        assert "AI 员工" in violations[0]["hits"]

    def test_transaction_description_with_robot_is_flagged(self):
        records = [
            {
                "id": 99,
                "description": "机器人代工执行任务 #42",
                "title": "正常发票",
            }
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "description")
        )
        assert len(violations) == 1
        assert violations[0]["record_id"] == 99
        assert violations[0]["field"] == "description"
        assert "机器人代工" in violations[0]["hits"]

    def test_case_insensitive_match(self):
        records = [
            {"id": 1, "title": "ai 代劳执行", "subject": "x"},
            {"id": 2, "title": "AI 代劳", "subject": "y"},
            {"id": 3, "title": "Ai 代劳", "subject": "z"},
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title",)
        )
        assert len(violations) == 3, "大小写都应命中"

    def test_empty_and_none_values_are_safe(self):
        records = [
            {"id": 1, "title": "", "subject": None},
            {"id": 2, "title": None, "subject": ""},
            {"id": 3, "title": "   ", "subject": "\n\t"},
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "subject")
        )
        assert violations == []

    def test_real_invoice_table_scan_with_clean_data(self, isolated_db):
        """端到端：真实 ``Invoice`` 表写入中性词，扫描器应放行。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=3001)

        from modstore_server.models import Invoice

        with sf() as session:
            session.add(
                Invoice(
                    user_id=3001,
                    order_ids_json='["ORD-CLEAN-1"]',
                    amount=99.0,
                    title="客户经理代开增值税普通发票",
                    invoice_type="personal",
                    status="pending",
                )
            )
            session.commit()

            rows = session.query(Invoice).all()
            records = [
                {"id": r.id, "title": r.title, "subject": r.reject_reason or ""}
                for r in rows
            ]

        violations = scan_records_for_forbidden_words(
            records, fields=("title", "subject")
        )
        assert violations == [], f"中性词账单不应被检出敏感词：{violations}"

    def test_real_invoice_table_scan_flags_dirty_data(self, isolated_db):
        """端到端：真实 ``Invoice`` 表写入「AI 代劳」字样，扫描器应检出。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=3002)

        from modstore_server.models import Invoice

        with sf() as session:
            session.add(
                Invoice(
                    user_id=3002,
                    order_ids_json='["ORD-DIRTY-1"]',
                    amount=99.0,
                    title="AI 代劳服务费",
                    invoice_type="personal",
                    status="pending",
                )
            )
            session.commit()

            rows = session.query(Invoice).all()
            records = [{"id": r.id, "title": r.title} for r in rows]

        violations = scan_records_for_forbidden_words(
            records, fields=("title",)
        )
        assert len(violations) >= 1
        assert any("AI 代劳" in v["hits"] for v in violations)


# --------------------------------------------------------------------------- #
# A4 · 通知语言使用中性身份
# --------------------------------------------------------------------------- #


class TestAcceptanceA4NotificationIdentity:
    """A4 · ``Notification.title`` / ``Notification.content`` 不应出现 FORBIDDEN_WORDS。"""

    def test_clean_notification_passes_scanner(self):
        records = [
            {
                "id": 1,
                "title": "您的客户经理已上线",
                "content": "专属助理为您服务",
            },
            {
                "id": 2,
                "title": "服务团队通知",
                "content": "您的服务团队已收到您的请求",
            },
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "content")
        )
        assert violations == []

    def test_notification_with_ai_assistant_is_flagged(self):
        records = [
            {
                "id": 1,
                "title": "AI 助理已处理您的请求",
                "content": "请确认",
            }
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "content")
        )
        assert len(violations) == 1
        assert violations[0]["field"] == "title"
        assert "AI 助理" in violations[0]["hits"]

    def test_notification_content_with_auto_reply_is_flagged(self):
        records = [
            {
                "id": 1,
                "title": "系统通知",
                "content": "此为自动回复，请勿回复",
            }
        ]
        violations = scan_records_for_forbidden_words(
            records, fields=("title", "content")
        )
        assert len(violations) == 1
        assert violations[0]["field"] == "content"
        assert "自动回复" in violations[0]["hits"]

    def test_real_notification_table_scan_with_clean_data(self, isolated_db):
        """端到端：真实 ``Notification`` 表写入中性词，扫描器应放行。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=3003)

        from modstore_server.models import Notification
        from modstore_server.notification_service import NotificationType

        from modstore_server.notification_service import create_notification

        create_notification(
            user_id=3003,
            notification_type=NotificationType.SYSTEM,
            title="您的客户经理已上线",
            content="专属助理将为您处理本次请求",
            data={"order_no": "ORD-CLEAN-NOTIF"},
        )

        with sf() as session:
            rows = session.query(Notification).all()
            records = [
                {"id": r.id, "title": r.title, "content": r.content} for r in rows
            ]

        violations = scan_records_for_forbidden_words(
            records, fields=("title", "content")
        )
        assert violations == [], f"中性词通知不应被检出敏感词：{violations}"

    def test_real_notification_table_scan_flags_dirty_data(self, isolated_db):
        """端到端：真实 ``Notification`` 表写入「AI 员工」字样，扫描器应检出。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=3004)

        from modstore_server.models import Notification

        with sf() as session:
            session.add(
                Notification(
                    user_id=3004,
                    kind="system",
                    title="AI 员工 #42 已完成任务",
                    content="AI 自动处理您的请求",
                    is_read=False,
                )
            )
            session.commit()

            rows = session.query(Notification).all()
            records = [
                {"id": r.id, "title": r.title, "content": r.content} for r in rows
            ]

        violations = scan_records_for_forbidden_words(
            records, fields=("title", "content")
        )
        assert len(violations) >= 1
        # 至少命中 "AI 员工" 或 "AI 自动"
        all_hits = [w for v in violations for w in v["hits"]]
        assert any("AI 员工" in h or "AI 自动" in h for h in all_hits)


# --------------------------------------------------------------------------- #
# 引用契约（自动化用例可被外部 CI 引用）
# --------------------------------------------------------------------------- #


#: ``acceptance_a3_bill_wording_no_ai_disclosure`` 引用此模块的 ``scan_records_for_forbidden_words``
#: 与 ``FORBIDDEN_WORDS`` 常量；CI 中可独立运行扫描全表，违规即 fail。
ACCEPTANCE_A3_FIXTURE_NAME = "acceptance_a3_bill_wording_no_ai_disclosure"

#: ``acceptance_a4_notification_identity_neutral`` 同理。
ACCEPTANCE_A4_FIXTURE_NAME = "acceptance_a4_notification_identity_neutral"
