"""测试 user_cs_change_request 模块 - 内部客服变更工单。"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from app.services.user_cs_change_request import (
    _CHANGE_TYPES,
    _STATUS_LABELS,
    _decorate,
    _find_row,
    _load_rows,
    _save_rows,
    build_change_request_wechat_message,
    build_ops_dispatch_task_description,
    create_change_request,
    list_change_requests,
    mark_change_request_ops_dispatched,
    mark_change_request_wechat_notified,
    update_change_request_status,
)


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    """将存储目录重定向到临时目录。"""
    from app.services import user_cs_change_request as mod

    def _mock_roots():
        return [tmp_path]

    monkeypatch.setattr(mod, "_store_roots", _mock_roots)
    return tmp_path


class TestDecorate:
    """测试 _decorate 辅助函数。"""

    def test_adds_change_type_label(self):
        row = {"change_type": "product_change", "status": "pending"}
        out = _decorate(row)
        assert out["change_type_label"] == "产品变更"
        assert out["status_label"] == "待处理"

    def test_unknown_change_type_falls_back(self):
        row = {"change_type": "unknown_type", "status": "pending"}
        out = _decorate(row)
        assert out["change_type_label"] == "unknown_type"

    def test_empty_change_type(self):
        row = {"change_type": "", "status": "pending"}
        out = _decorate(row)
        assert out["change_type_label"] == "变更"

    def test_missing_change_type(self):
        row = {"status": "pending"}
        out = _decorate(row)
        assert out["change_type_label"] == "变更"

    def test_unknown_status_falls_back(self):
        row = {"change_type": "bug_fix", "status": "unknown_status"}
        out = _decorate(row)
        assert out["status_label"] == "unknown_status"

    def test_default_status_is_pending(self):
        row = {"change_type": "bug_fix"}
        out = _decorate(row)
        assert out["status_label"] == "待处理"

    def test_does_not_mutate_original(self):
        row = {"change_type": "bug_fix", "status": "pending"}
        out = _decorate(row)
        assert "change_type_label" not in row
        assert "change_type_label" in out


class TestFindRow:
    """测试 _find_row 辅助函数。"""

    def test_finds_matching_row(self):
        rows = [{"id": "abc123"}, {"id": "def456"}]
        assert _find_row(rows, "abc123") == rows[0]

    def test_returns_none_when_not_found(self):
        rows = [{"id": "abc123"}]
        assert _find_row(rows, "xyz") is None

    def test_empty_rows(self):
        assert _find_row([], "abc") is None

    def test_string_id_comparison(self):
        rows = [{"id": 123}]
        assert _find_row(rows, "123") is not None

    def test_first_match_wins(self):
        rows = [{"id": "a"}, {"id": "a"}]
        result = _find_row(rows, "a")
        assert result is rows[0]


class TestLoadSaveRows:
    """测试 _load_rows / _save_rows 持久化。"""

    def test_load_empty_file(self, _tmp_store):
        rows = _load_rows(99999)
        assert rows == []

    def test_save_and_load_roundtrip(self, _tmp_store):
        data = [{"id": "t1", "title": "测试"}]
        _save_rows(100, data)
        loaded = _load_rows(100)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "t1"

    def test_load_corrupted_json(self, _tmp_store):
        path = _tmp_store / "100.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        rows = _load_rows(100)
        assert rows == []

    def test_load_non_dict_rows(self, _tmp_store):
        path = _tmp_store / "100.json"
        path.write_text(json.dumps(["not", "dict"]), encoding="utf-8")
        rows = _load_rows(100)
        assert rows == []

    def test_load_non_list_requests(self, _tmp_store):
        path = _tmp_store / "100.json"
        path.write_text(json.dumps({"requests": "not_a_list"}), encoding="utf-8")
        rows = _load_rows(100)
        assert rows == []

    def test_load_filters_non_dict_entries(self, _tmp_store):
        path = _tmp_store / "100.json"
        path.write_text(json.dumps({"requests": [{"id": "a"}, "bad", 42]}), encoding="utf-8")
        rows = _load_rows(100)
        assert len(rows) == 1


class TestCreateChangeRequest:
    """测试创建变更工单。"""

    def test_create_valid_request(self):
        result = create_change_request(
            100,
            change_type="product_change",
            title="修改产品规格",
            description="需要修改A产品规格",
            priority="high",
            username="张三",
        )
        assert result["change_type"] == "product_change"
        assert result["change_type_label"] == "产品变更"
        assert result["title"] == "修改产品规格"
        assert result["status"] == "pending"
        assert result["status_label"] == "待处理"
        assert result["priority"] == "high"
        assert result["username"] == "张三"
        assert "id" in result
        assert "ticket_no" in result
        assert "created_at" in result

    def test_create_generates_ticket_no(self):
        result = create_change_request(100, change_type="bug_fix", title="修复问题")
        assert result["ticket_no"].startswith("CR-100-")

    def test_create_truncates_long_title(self):
        result = create_change_request(100, change_type="bug_fix", title="x" * 300)
        assert len(result["title"]) <= 256

    def test_create_truncates_long_description(self):
        result = create_change_request(
            100, change_type="bug_fix", title="t", description="d" * 10000
        )
        assert len(result["description"]) <= 8000

    def test_create_invalid_change_type_raises(self):
        with pytest.raises(ValueError, match="未知变更类型"):
            create_change_request(100, change_type="invalid_type", title="t")

    def test_create_empty_title_raises(self):
        with pytest.raises(ValueError, match="标题不能为空"):
            create_change_request(100, change_type="bug_fix", title="")

    def test_create_blank_title_raises(self):
        with pytest.raises(ValueError, match="标题不能为空"):
            create_change_request(100, change_type="bug_fix", title="   ")

    def test_create_all_change_types(self):
        for ct in _CHANGE_TYPES:
            result = create_change_request(100, change_type=ct, title=f"测试{ct}")
            assert result["change_type"] == ct

    def test_create_default_priority(self):
        result = create_change_request(100, change_type="bug_fix", title="t")
        assert result["priority"] == "normal"

    def test_create_default_source(self):
        result = create_change_request(100, change_type="bug_fix", title="t")
        assert result["source"] == "enterprise_portal"


class TestListChangeRequests:
    """测试列出变更工单。"""

    def test_list_empty(self):
        result = list_change_requests(99999)
        assert result == []

    def test_list_returns_created_requests(self):
        create_change_request(200, change_type="bug_fix", title="工单1")
        create_change_request(200, change_type="feature_request", title="工单2")
        result = list_change_requests(200)
        assert len(result) == 2

    def test_list_decorates_rows(self):
        create_change_request(200, change_type="bug_fix", title="t")
        result = list_change_requests(200)
        assert result[0]["change_type_label"] == "问题修复"
        assert result[0]["status_label"] == "待处理"

    def test_list_isolation_between_users(self):
        create_change_request(300, change_type="bug_fix", title="用户300")
        create_change_request(400, change_type="bug_fix", title="用户400")
        result = list_change_requests(300)
        assert len(result) == 1
        assert result[0]["title"] == "用户300"


class TestUpdateChangeRequestStatus:
    """测试更新变更工单状态。"""

    def test_update_status_to_in_progress(self):
        created = create_change_request(500, change_type="bug_fix", title="t")
        result = update_change_request_status(
            500, created["id"], status="in_progress", admin_note="开始处理"
        )
        assert result["status"] == "in_progress"
        assert result["status_label"] == "处理中"
        assert result["admin_note"] == "开始处理"

    def test_update_status_to_resolved(self):
        created = create_change_request(500, change_type="bug_fix", title="t")
        result = update_change_request_status(500, created["id"], status="resolved")
        assert result["status"] == "resolved"

    def test_update_invalid_status_raises(self):
        created = create_change_request(500, change_type="bug_fix", title="t")
        with pytest.raises(ValueError, match="未知状态"):
            update_change_request_status(500, created["id"], status="invalid")

    def test_update_nonexistent_ticket_raises(self):
        with pytest.raises(ValueError, match="未找到该变更工单"):
            update_change_request_status(500, "nonexistent_id", status="resolved")

    def test_update_empty_admin_note_not_saved(self):
        created = create_change_request(500, change_type="bug_fix", title="t")
        result = update_change_request_status(
            500, created["id"], status="in_progress", admin_note="   "
        )
        assert "admin_note" not in result

    def test_all_valid_statuses(self):
        created = create_change_request(500, change_type="bug_fix", title="t")
        for status in _STATUS_LABELS:
            result = update_change_request_status(500, created["id"], status=status)
            assert result["status"] == status


class TestMarkOpsDispatched:
    """测试标记运维派单。"""

    def test_mark_dispatched_with_job_id(self):
        created = create_change_request(600, change_type="ops_support", title="t")
        result = mark_change_request_ops_dispatched(600, created["id"], job_id="JOB-001")
        assert result["ops_dispatch_job_id"] == "JOB-001"
        assert "ops_dispatched_at" in result

    def test_mark_dispatched_with_error(self):
        created = create_change_request(600, change_type="ops_support", title="t")
        result = mark_change_request_ops_dispatched(600, created["id"], error="派单失败")
        assert result["ops_dispatch_error"] == "派单失败"
        assert "ops_dispatch_job_id" not in result

    def test_mark_dispatched_nonexistent_raises(self):
        with pytest.raises(ValueError, match="未找到该变更工单"):
            mark_change_request_ops_dispatched(600, "nonexistent", job_id="J1")


class TestMarkWechatNotified:
    """测试标记微信通知。"""

    def test_mark_wechat_notified(self):
        created = create_change_request(700, change_type="bug_fix", title="t")
        result = mark_change_request_wechat_notified(700, created["id"])
        assert "wechat_notified_at" in result

    def test_mark_wechat_notified_nonexistent_raises(self):
        with pytest.raises(ValueError, match="未找到该变更工单"):
            mark_change_request_wechat_notified(700, "nonexistent")


class TestBuildOpsDispatchTaskDescription:
    """测试构建运维派单描述。"""

    def test_build_description_with_all_fields(self):
        row = {
            "title": "修改产品",
            "description": "需要修改A产品",
            "change_type_label": "产品变更",
            "ticket_no": "CR-100-0001",
        }
        desc = build_ops_dispatch_task_description(row, market_user_id=100, client_name="张三")
        assert "修改产品" in desc
        assert "张三" in desc
        assert "100" in desc
        assert "产品变更" in desc
        assert "CR-100-0001" in desc

    def test_build_description_without_description(self):
        row = {"title": "标题"}
        desc = build_ops_dispatch_task_description(row, market_user_id=1)
        assert "标题" in desc
        assert "说明" not in desc

    def test_build_description_fallback_username(self):
        row = {"title": "t", "username": "李四"}
        desc = build_ops_dispatch_task_description(row, market_user_id=1)
        assert "李四" in desc


class TestBuildWechatMessage:
    """测试构建微信通知消息。"""

    def test_build_message(self):
        row = {
            "title": "产品变更",
            "status_label": "处理中",
            "ticket_no": "CR-100-0001",
        }
        msg = build_change_request_wechat_message(row, client_name="张三")
        assert "张三" in msg
        assert "产品变更" in msg
        assert "处理中" in msg
        assert "CR-100-0001" in msg

    def test_build_message_default_client_name(self):
        row = {"title": "t", "status": "pending"}
        msg = build_change_request_wechat_message(row)
        assert "客户" in msg

    def test_build_message_fallback_status(self):
        row = {"title": "t", "status": "unknown"}
        msg = build_change_request_wechat_message(row, client_name="x")
        assert "unknown" in msg
