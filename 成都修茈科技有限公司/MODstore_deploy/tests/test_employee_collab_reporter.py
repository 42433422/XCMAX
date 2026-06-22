"""employee_collab_reporter 单测：部门映射 / 线程幂等 / 去重 / mentions=[] 无副作用 / 行动条目聚合。

conftest 已把 DB 指向临时 SQLite（``MODSTORE_DB_PATH``）；这里显式 ``init_db()`` 建表。
"""

from __future__ import annotations

import pytest

from modstore_server import employee_collab_reporter as reporter
from modstore_server.models import (
    EmployeeCollabMessage,
    EmployeeCollabThread,
    EmployeeSuggestion,
    get_session_factory,
    init_db,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


def _count(model) -> int:
    sf = get_session_factory()
    with sf() as s:
        return int(s.query(model).count())


def test_dept_for_employee_known_and_fallback():
    assert reporter._dept_for_employee("fhd-core-maintainer") == "prod_software"
    # 跨部门取插入序首个：daily-orchestrator 先出现在 prod_web
    assert reporter._dept_for_employee("daily-orchestrator") == "prod_web"
    assert reporter._dept_for_employee("totally-unknown") == "company"
    assert reporter._dept_for_employee("") == "company"


def test_get_or_create_dept_thread_idempotent():
    tid1 = reporter.get_or_create_dept_thread("prod_software")
    tid2 = reporter.get_or_create_dept_thread("prod_software")
    assert tid1 and tid1 == tid2
    sf = get_session_factory()
    with sf() as s:
        row = s.get(EmployeeCollabThread, tid1)
        assert row is not None
        assert row.title == reporter._stable_thread_title("prod_software")
        assert "dept=prod_software" in row.title


def test_report_dedupe_and_no_suggestion_side_effect():
    before_sugg = _count(EmployeeSuggestion)
    out1 = reporter.report_staged_change(
        staged_id=777, branch="auto/daily-z", files=5, pr_url="https://x/pr/9"
    )
    assert out1["ok"] and not out1["skipped"]
    out2 = reporter.report_staged_change(
        staged_id=777, branch="auto/daily-z", files=5, pr_url="https://x/pr/9"
    )
    assert out2["skipped"] is True
    # mentions=[] 绝不能衍生 collab_mention 建议
    assert _count(EmployeeSuggestion) == before_sugg
    sf = get_session_factory()
    with sf() as s:
        msg = (
            s.query(EmployeeCollabMessage)
            .filter(EmployeeCollabMessage.payload_json.like('%"staged|777"%'))
            .first()
        )
        assert msg is not None
        assert msg.sender_employee_id == "daily-orchestrator"
        assert msg.mentions_json == "[]"
        assert "staged|777" in msg.payload_json


def test_report_action_items_groups_per_employee(monkeypatch):
    canned = [
        {
            "employee_id": "fhd-core-maintainer",
            "employee_label": "FHD核心",
            "priority": "P0",
            "kind": "patch",
            "text": "修复 A",
        },
        {
            "employee_id": "fhd-core-maintainer",
            "employee_label": "FHD核心",
            "priority": "P1",
            "kind": "update",
            "text": "补文档 B",
        },
        {
            "employee_id": "site-content-editor",
            "employee_label": "站点编辑",
            "priority": "P2",
            "kind": "update",
            "text": "改文案 C",
        },
        {
            "employee_id": "",
            "priority": "P0",
            "kind": "patch",
            "text": "无主条目应跳过",
        },
    ]
    monkeypatch.setattr(
        "modstore_server.digest_action_items.list_action_items",
        lambda **kw: canned,
    )
    out = reporter.report_action_items(day="2026-06-22", record_id=42)
    assert out["ok"] and out["employees"] == 2
    assert out["posted"] == 2
    # 再跑 → 全部去重
    out2 = reporter.report_action_items(day="2026-06-22", record_id=42)
    assert out2["posted"] == 0 and out2["skipped"] == 2
    # 发送者落到正确部门线程
    fhd_thread = reporter.get_or_create_dept_thread("prod_software")
    sf = get_session_factory()
    with sf() as s:
        msg = (
            s.query(EmployeeCollabMessage)
            .filter(
                EmployeeCollabMessage.payload_json.like(
                    '%"actions|2026-06-22|fhd-core-maintainer"%'
                )
            )
            .first()
        )
        assert msg is not None
        assert msg.thread_id == fhd_thread
        assert msg.sender_employee_id == "fhd-core-maintainer"
        assert "共 2 项" in msg.content
