"""测试 ai_group_chat_service 的补充分支覆盖（第二批）。

覆盖目标（第一批 test_ai_group_chat_service_branch_cov.py 未覆盖的方法与分支）：
- _dispatch_difficulty: large_markers / simple_markers / 长度边界 / medium
- _preferred_single_dispatch_target: 各关键词组合 / 空候选 / 兜底
- _build_dispatch_assignments: should_split / 非 split / 空成员
- _super_employee_focus: 各 employee_id / 测试关键词 / 默认
- _format_assigned_task: 各 employee_id / 未知 employee_id
- _chat_friendly_summary: 代码块 / markdown / 长度截断 / 空文本
- _clean_chat_summary_line: 临时路径 / markdown 链接 / token 替换
- _compact_public_acceptance_body: 各字段缺失 / 成员行截断
- _clean_public_chat_body: 临时路径 / markdown / relay task id
- _cap_public_chat_body: 短文本 / 长文本截断
- _format_work_acceptance_message: all_ok / needs_review / 各字段缺失
- _append_work_acceptance_if_ready: 各分支（无 work_order_id / 无 rows / 已存在 / 未就绪 / 就绪）
- _public_status_label: 各状态 / 未知状态
- _strip_label_from_body: 有 label / 无 label / 空文本
- _report_relay_task_id: 各分支
- _normalize_branch_context: 各分支（origin/ / 特殊字符 / 空 / HEAD）
- delete_message: 各分支（空 id / 不存在 / 非 user 消息 / 成功）
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.application.ai_group_chat_service as group_chat_module
from app.application.ai_group_chat_service import (
    CHAT_ACCEPTANCE_SUMMARY_CHARS,
    CHAT_REPORT_SUMMARY_CHARS,
    MAX_RESPONDERS,
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
    PUBLIC_CHAT_BODY_MAX_CHARS,
    SUPER_DISCUSSION_DEFAULT_ROUNDS,
    SUPER_DISCUSSION_MAX_ROUNDS,
    AiGroupChatService,
)


# ---------------------------------------------------------------------------
# helpers（与第一批保持一致）
# ---------------------------------------------------------------------------


def fake_departments() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "ops_partner": {"label": "O-B 伙伴部"},
        "prod_web": {"label": "P-W 网站部"},
        "prod_mod": {"label": "P-M Mod 部"},
        "prod_software": {"label": "P-S 软件部"},
        "shared_retention": {"label": "S-R 归档部"},
    }


def fake_enterprise_departments() -> dict[str, dict[str, str]]:
    return {
        "tools": {"label": "工具层"},
        "execution": {"label": "执行层"},
        "service": {"label": "服务层"},
        "management": {"label": "管理层"},
    }


def make_completion(seen: list[dict] | None = None, content: str = "收到"):
    async def completion(messages):
        if seen is not None:
            seen.append({"system": messages[0]["content"], "user": messages[1]["content"]})
        return {"success": True, "content": content, "error": ""}

    return completion


def make_service(
    tmp_path: Path,
    seen: list[dict] | None = None,
    employees=None,
    mode: str = "admin",
    executor=None,
    completion_fn=None,
    department_loader=None,
) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion_fn or make_completion(seen),
        employee_executor_fn=executor,
        department_loader=department_loader or (fake_enterprise_departments if mode == "enterprise" else fake_departments),
        employee_loader=(employees if callable(employees) else (lambda: employees or [])),
        mode=mode,
    )


def _make_super_members() -> list[dict]:
    """构造 3 个超级员工成员。"""
    return [
        {"employee_id": "codex-super-employee", "name": "Codex", "avatar": "", "summary": "Codex"},
        {"employee_id": "cursor-super-employee", "name": "Cursor", "avatar": "", "summary": "Cursor"},
        {"employee_id": "claude-super-employee", "name": "Claude", "avatar": "", "summary": "Claude"},
    ]


# ---------------------------------------------------------------------------
# _dispatch_difficulty
# ---------------------------------------------------------------------------


class TestDispatchDifficultyEdge:
    """_dispatch_difficulty 的补充分支覆盖。"""

    def test_dispatch_difficulty_large_with_full_chain(self):
        assert AiGroupChatService._dispatch_difficulty("全链路重构") == "large"

    def test_dispatch_difficulty_large_with_entire_set(self):
        assert AiGroupChatService._dispatch_difficulty("整套架构") == "large"

    def test_dispatch_difficulty_large_with_multi_platform(self):
        assert AiGroupChatService._dispatch_difficulty("多端并行") == "large"

    def test_dispatch_difficulty_large_with_large_scale(self):
        assert AiGroupChatService._dispatch_difficulty("大规模重构") == "large"

    def test_dispatch_difficulty_large_with_multiple_modules(self):
        assert AiGroupChatService._dispatch_difficulty("多个模块一起工作") == "large"

    def test_dispatch_difficulty_simple_with_small_bug(self):
        assert AiGroupChatService._dispatch_difficulty("小bug 修复") == "simple"

    def test_dispatch_difficulty_simple_with_small_bug_space(self):
        assert AiGroupChatService._dispatch_difficulty("小 bug 修复") == "simple"

    def test_dispatch_difficulty_simple_with_copy(self):
        assert AiGroupChatService._dispatch_difficulty("复制文案") == "simple"

    def test_dispatch_difficulty_simple_with_delete(self):
        assert AiGroupChatService._dispatch_difficulty("删除文件") == "simple"

    def test_dispatch_difficulty_simple_with_long_press(self):
        assert AiGroupChatService._dispatch_difficulty("长按手势") == "simple"

    def test_dispatch_difficulty_simple_with_style(self):
        assert AiGroupChatService._dispatch_difficulty("样式调整") == "simple"

    def test_dispatch_difficulty_simple_with_small_issue(self):
        assert AiGroupChatService._dispatch_difficulty("小问题") == "simple"

    def test_dispatch_difficulty_simple_with_short_text(self):
        assert AiGroupChatService._dispatch_difficulty("短任务") == "simple"

    def test_dispatch_difficulty_simple_with_exact_90_chars(self):
        text = "a" * 90
        assert AiGroupChatService._dispatch_difficulty(text) == "simple"

    def test_dispatch_difficulty_medium_with_long_text_no_markers(self):
        text = "a" * 91
        assert AiGroupChatService._dispatch_difficulty(text) == "medium"

    def test_dispatch_difficulty_medium_with_no_markers(self):
        text = "这是一个中等复杂度的任务描述，没有命中任何关键词，需要超过九十字符才能进入中等难度分级" * 3
        assert AiGroupChatService._dispatch_difficulty(text) == "medium"

    def test_dispatch_difficulty_empty_string(self):
        assert AiGroupChatService._dispatch_difficulty("") == "simple"

    def test_dispatch_difficulty_none(self):
        assert AiGroupChatService._dispatch_difficulty(None) == "simple"

    def test_dispatch_difficulty_large_takes_precedence_over_simple(self):
        assert AiGroupChatService._dispatch_difficulty("全链路小问题") == "large"


# ---------------------------------------------------------------------------
# _preferred_single_dispatch_target
# ---------------------------------------------------------------------------


class TestPreferredSingleDispatchTargetEdge:
    """_preferred_single_dispatch_target 的补充分支覆盖。"""

    def test_preferred_empty_candidates_returns_none(self):
        assert AiGroupChatService._preferred_single_dispatch_target([], "任务") is None

    def test_preferred_arch_keywords_returns_claude(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "架构方案")
        assert result["employee_id"] == "claude-super-employee"

    def test_preferred_review_keywords_returns_claude(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "评审验收")
        assert result["employee_id"] == "claude-super-employee"

    def test_preferred_planning_keywords_returns_claude(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "规划路由")
        assert result["employee_id"] == "claude-super-employee"

    def test_preferred_dispatch_keywords_returns_claude(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "分流")
        assert result["employee_id"] == "claude-super-employee"

    def test_preferred_android_only_returns_cursor(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "android 页面")
        assert result["employee_id"] == "cursor-super-employee"

    def test_preferred_mobile_only_returns_cursor(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "移动端手机")
        assert result["employee_id"] == "cursor-super-employee"

    def test_preferred_compose_kotlin_returns_cursor(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "compose kotlin")
        assert result["employee_id"] == "cursor-super-employee"

    def test_preferred_ui_ux_returns_cursor(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "ui ux 体验")
        assert result["employee_id"] == "cursor-super-employee"

    def test_preferred_android_with_backend_returns_codex(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "android 后端接口")
        assert result["employee_id"] == "codex-super-employee"

    def test_preferred_android_with_api_returns_codex(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "移动端 api")
        assert result["employee_id"] == "codex-super-employee"

    def test_preferred_android_with_pytest_returns_codex(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "手机 pytest 测试")
        assert result["employee_id"] == "codex-super-employee"

    def test_preferred_default_returns_codex(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "普通任务")
        assert result["employee_id"] == "codex-super-employee"

    def test_preferred_falls_back_to_first_super_employee(self):
        candidates = [
            {"employee_id": "other-emp", "name": "Other"},
            {"employee_id": "cursor-super-employee", "name": "Cursor"},
        ]
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "普通任务")
        assert result["employee_id"] == "cursor-super-employee"

    def test_preferred_falls_back_to_first_candidate(self):
        candidates = [
            {"employee_id": "other-emp1", "name": "Other1"},
            {"employee_id": "other-emp2", "name": "Other2"},
        ]
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "普通任务")
        assert result["employee_id"] == "other-emp1"

    def test_preferred_empty_task(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, "")
        assert result["employee_id"] == "codex-super-employee"

    def test_preferred_none_task(self):
        candidates = _make_super_members()
        result = AiGroupChatService._preferred_single_dispatch_target(candidates, None)
        assert result["employee_id"] == "codex-super-employee"


# ---------------------------------------------------------------------------
# _build_dispatch_assignments
# ---------------------------------------------------------------------------


class TestBuildDispatchAssignmentsEdge:
    """_build_dispatch_assignments 的补充分支覆盖。"""

    def test_build_assignments_empty_members(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._build_dispatch_assignments("任务", [])
        assert result == []

    def test_build_assignments_single_member_no_split(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "员工1"}]
        result = svc._build_dispatch_assignments("任务", members)
        assert len(result) == 1
        assert result[0]["assignment_focus"] == "主负责人"
        assert result[0]["assigned_task"] == "任务"

    def test_build_assignments_multiple_non_super_members_no_split(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [
            {"employee_id": "e1", "name": "员工1"},
            {"employee_id": "e2", "name": "员工2"},
        ]
        result = svc._build_dispatch_assignments("任务", members)
        assert len(result) == 2
        for r in result:
            assert r["assignment_focus"] == "主负责人"
            assert r["assigned_task"] == "任务"

    def test_build_assignments_two_super_members_triggers_split(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = _make_super_members()[:2]
        result = svc._build_dispatch_assignments("任务", members)
        assert len(result) == 2
        for r in result:
            assert "assignment_focus" in r
            assert "assigned_task" in r
            assert "任务" in r["assigned_task"]

    def test_build_assignments_three_super_members_triggers_split(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = _make_super_members()
        result = svc._build_dispatch_assignments("任务", members)
        assert len(result) == 3
        focuses = {r["assignment_focus"] for r in result}
        assert len(focuses) == 3

    def test_build_assignments_mixed_super_and_non_super_no_split(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [
            {"employee_id": "codex-super-employee", "name": "Codex"},
            {"employee_id": "e1", "name": "普通员工"},
        ]
        result = svc._build_dispatch_assignments("任务", members)
        assert len(result) == 2
        for r in result:
            assert r["assignment_focus"] == "主负责人"


# ---------------------------------------------------------------------------
# _super_employee_focus
# ---------------------------------------------------------------------------


class TestSuperEmployeeFocusEdge:
    """_super_employee_focus 的补充分支覆盖。"""

    def test_super_employee_focus_cursor(self):
        result = AiGroupChatService._super_employee_focus("cursor-super-employee", "任务")
        assert "移动端" in result or "前端" in result

    def test_super_employee_focus_codex(self):
        result = AiGroupChatService._super_employee_focus("codex-super-employee", "任务")
        assert "服务端" in result or "接口" in result

    def test_super_employee_focus_claude(self):
        result = AiGroupChatService._super_employee_focus("claude-super-employee", "任务")
        assert "方案" in result or "验收" in result

    def test_super_employee_focus_other_with_test_keyword(self):
        result = AiGroupChatService._super_employee_focus("other-emp", "测试任务")
        assert "验收" in result

    def test_super_employee_focus_other_with_acceptance_keyword(self):
        result = AiGroupChatService._super_employee_focus("other-emp", "验收任务")
        assert "验收" in result

    def test_super_employee_focus_other_no_keywords(self):
        result = AiGroupChatService._super_employee_focus("other-emp", "普通任务")
        assert "职责" in result

    def test_super_employee_focus_empty_task(self):
        result = AiGroupChatService._super_employee_focus("other-emp", "")
        assert "职责" in result

    def test_super_employee_focus_none_task(self):
        result = AiGroupChatService._super_employee_focus("other-emp", None)
        assert "职责" in result


# ---------------------------------------------------------------------------
# _format_assigned_task
# ---------------------------------------------------------------------------


class TestFormatAssignedTaskEdge:
    """_format_assigned_task 的补充分支覆盖。"""

    def test_format_assigned_task_cursor(self):
        result = AiGroupChatService._format_assigned_task(
            original_task="原始任务", employee_id="cursor-super-employee", focus="移动端"
        )
        assert "移动端" in result
        assert "原始任务" in result
        assert "移动端/前端" in result

    def test_format_assigned_task_codex(self):
        result = AiGroupChatService._format_assigned_task(
            original_task="原始任务", employee_id="codex-super-employee", focus="服务端"
        )
        assert "服务端" in result
        assert "原始任务" in result
        assert "服务端/接口" in result

    def test_format_assigned_task_claude(self):
        result = AiGroupChatService._format_assigned_task(
            original_task="原始任务", employee_id="claude-super-employee", focus="方案"
        )
        assert "方案" in result
        assert "原始任务" in result
        assert "验收口径" in result

    def test_format_assigned_task_unknown_employee(self):
        result = AiGroupChatService._format_assigned_task(
            original_task="原始任务", employee_id="unknown-emp", focus="普通"
        )
        assert "普通" in result
        assert "原始任务" in result
        assert "职责范围" in result

    def test_format_assigned_task_empty_focus(self):
        result = AiGroupChatService._format_assigned_task(
            original_task="原始任务", employee_id="codex-super-employee", focus=""
        )
        assert "原始任务" in result


# ---------------------------------------------------------------------------
# _chat_friendly_summary
# ---------------------------------------------------------------------------


class TestChatFriendlySummaryEdge:
    """_chat_friendly_summary 的补充分支覆盖。"""

    def test_chat_friendly_summary_empty_string(self):
        assert AiGroupChatService._chat_friendly_summary("") == ""

    def test_chat_friendly_summary_none(self):
        assert AiGroupChatService._chat_friendly_summary(None) == ""

    def test_chat_friendly_summary_plain_text(self):
        result = AiGroupChatService._chat_friendly_summary("简单文本")
        assert "简单文本" in result

    def test_chat_friendly_summary_with_code_block(self):
        text = "```\ncode here\n```\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "实际内容" in result
        assert "code" not in result

    def test_chat_friendly_summary_with_markdown_header(self):
        text = "# 标题\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "实际内容" in result
        assert "标题" not in result or "实际内容" in result

    def test_chat_friendly_summary_with_markdown_link(self):
        text = "[链接文字](http://example.com)\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "链接文字" in result
        assert "http://example.com" not in result

    def test_chat_friendly_summary_with_broken_markdown_link(self):
        text = "[链接文字（不完整\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "实际内容" in result

    def test_chat_friendly_summary_with_table_row(self):
        text = "| 列1 | 列2 |\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "实际内容" in result
        assert "列1" not in result

    def test_chat_friendly_summary_with_horizontal_rule(self):
        text = "---\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "实际内容" in result

    def test_chat_friendly_summary_with_bold_token(self):
        text = "**加粗**\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "加粗" in result
        assert "**" not in result

    def test_chat_friendly_summary_with_underscore_token(self):
        text = "__下划线__\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "下划线" in result
        assert "__" not in result

    def test_chat_friendly_summary_with_backtick_token(self):
        text = "`代码`\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "代码" in result
        assert "`" not in result

    def test_chat_friendly_summary_with_temp_path(self):
        text = "路径 /var/folders/abc123 文件\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "临时执行工作区" in result
        assert "/var/folders" not in result

    def test_chat_friendly_summary_with_private_temp_path(self):
        text = "路径 /private/var/folders/abc123 文件\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "临时执行工作区" in result

    def test_chat_friendly_summary_truncates_to_limit(self):
        text = "a" * (CHAT_REPORT_SUMMARY_CHARS + 100)
        result = AiGroupChatService._chat_friendly_summary(text, limit=50, include_detail_note=False)
        assert len(result) <= 51  # 50 + …
        assert result.endswith("…")

    def test_chat_friendly_summary_adds_detail_note(self):
        text = "短内容\n" + "b" * 500
        result = AiGroupChatService._chat_friendly_summary(text, limit=CHAT_REPORT_SUMMARY_CHARS)
        assert "详细结果已保留" in result

    def test_chat_friendly_summary_no_detail_note_when_short(self):
        text = "短内容"
        result = AiGroupChatService._chat_friendly_summary(text, limit=CHAT_REPORT_SUMMARY_CHARS)
        assert "详细结果已保留" not in result

    def test_chat_friendly_summary_no_detail_note_when_disabled(self):
        text = "短内容\n" + "b" * 200
        result = AiGroupChatService._chat_friendly_summary(
            text, limit=CHAT_REPORT_SUMMARY_CHARS, include_detail_note=False
        )
        assert "详细结果已保留" not in result

    def test_chat_friendly_summary_multiple_lines_joined(self):
        text = "第一行\n第二行\n第三行"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "第一行" in result
        assert "第二行" in result

    def test_chat_friendly_summary_stops_at_3_lines(self):
        text = "第一行\n第二行\n第三行\n第四行\n第五行"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "第一行" in result
        assert "第四行" not in result

    def test_chat_friendly_summary_carriage_return_normalized(self):
        text = "第一行\r\n第二行\r第三行"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "第一行" in result
        assert "第二行" in result

    def test_chat_friendly_summary_only_code_block_returns_fallback(self):
        text = "```\ncode only\n```"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert result  # 不为空，回退到原始文本

    def test_chat_friendly_summary_list_items(self):
        text = "- 项目1\n- 项目2\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "项目1" in result or "实际内容" in result

    def test_chat_friendly_summary_quote_items(self):
        text = "> 引用\n实际内容"
        result = AiGroupChatService._chat_friendly_summary(text)
        assert "引用" in result or "实际内容" in result


# ---------------------------------------------------------------------------
# _clean_chat_summary_line
# ---------------------------------------------------------------------------


class TestCleanChatSummaryLineEdge:
    """_clean_chat_summary_line 的补充分支覆盖。"""

    def test_clean_chat_summary_line_plain_text(self):
        result = AiGroupChatService._clean_chat_summary_line("简单文本")
        assert result == "简单文本"

    def test_clean_chat_summary_line_temp_path(self):
        result = AiGroupChatService._clean_chat_summary_line("路径 /var/folders/abc 文件")
        assert "临时执行工作区" in result
        assert "/var/folders" not in result

    def test_clean_chat_summary_line_private_temp_path(self):
        result = AiGroupChatService._clean_chat_summary_line("路径 /private/var/folders/abc 文件")
        assert "临时执行工作区" in result

    def test_clean_chat_summary_line_markdown_link(self):
        result = AiGroupChatService._clean_chat_summary_line("[文字](http://x.com) 内容")
        assert "文字" in result
        assert "http://x.com" not in result

    def test_clean_chat_summary_line_broken_markdown_link(self):
        result = AiGroupChatService._clean_chat_summary_line("[文字（不完整 内容")
        assert "文字" in result

    def test_clean_chat_summary_line_bold_token(self):
        result = AiGroupChatService._clean_chat_summary_line("**加粗** 内容")
        assert "加粗" in result
        assert "**" not in result

    def test_clean_chat_summary_line_underscore_token(self):
        result = AiGroupChatService._clean_chat_summary_line("__下划线__ 内容")
        assert "下划线" in result
        assert "__" not in result

    def test_clean_chat_summary_line_backtick_token(self):
        result = AiGroupChatService._clean_chat_summary_line("`代码` 内容")
        assert "代码" in result
        assert "`" not in result

    def test_clean_chat_summary_line_strips_trailing_punctuation(self):
        result = AiGroupChatService._clean_chat_summary_line("内容；，。 ")
        assert result == "内容"

    def test_clean_chat_summary_line_collapses_whitespace(self):
        result = AiGroupChatService._clean_chat_summary_line("内容    多空格")
        assert "  " not in result

    def test_clean_chat_summary_line_empty(self):
        assert AiGroupChatService._clean_chat_summary_line("") == ""

    def test_clean_chat_summary_line_none(self):
        assert AiGroupChatService._clean_chat_summary_line(None) == ""


# ---------------------------------------------------------------------------
# _cap_public_chat_body
# ---------------------------------------------------------------------------


class TestCapPublicChatBodyEdge:
    """_cap_public_chat_body 的补充分支覆盖。"""

    def test_cap_public_chat_body_short_text(self):
        result = AiGroupChatService._cap_public_chat_body("短文本", limit=100)
        assert result == "短文本"

    def test_cap_public_chat_body_exact_limit(self):
        text = "a" * 100
        result = AiGroupChatService._cap_public_chat_body(text, limit=100)
        assert result == text

    def test_cap_public_chat_body_over_limit(self):
        text = "a" * 200
        result = AiGroupChatService._cap_public_chat_body(text, limit=100)
        assert len(result) > 100  # 包含后缀
        assert "折叠" in result
        assert result.startswith("a" * 100)

    def test_cap_public_chat_body_default_limit(self):
        text = "a" * (PUBLIC_CHAT_BODY_MAX_CHARS + 100)
        result = AiGroupChatService._cap_public_chat_body(text)
        assert "折叠" in result

    def test_cap_public_chat_body_empty(self):
        assert AiGroupChatService._cap_public_chat_body("") == ""

    def test_cap_public_chat_body_none(self):
        assert AiGroupChatService._cap_public_chat_body(None) == ""

    def test_cap_public_chat_body_strips_whitespace(self):
        result = AiGroupChatService._cap_public_chat_body("  短文本  ", limit=100)
        assert result == "短文本"


# ---------------------------------------------------------------------------
# _clean_public_chat_body
# ---------------------------------------------------------------------------


class TestCleanPublicChatBodyEdge:
    """_clean_public_chat_body 的补充分支覆盖。"""

    def test_clean_public_chat_body_plain_text(self):
        result = AiGroupChatService._clean_public_chat_body("简单文本")
        assert result == "简单文本"

    def test_clean_public_chat_body_temp_path(self):
        result = AiGroupChatService._clean_public_chat_body("路径 /var/folders/abc 文件")
        assert "临时执行工作区" in result
        assert "/var/folders" not in result

    def test_clean_public_chat_body_private_temp_path(self):
        result = AiGroupChatService._clean_public_chat_body("路径 /private/var/folders/abc 文件")
        assert "临时执行工作区" in result

    def test_clean_public_chat_body_markdown_link(self):
        result = AiGroupChatService._clean_public_chat_body("[文字](http://x.com) 内容")
        assert "文字" in result
        assert "http://x.com" not in result

    def test_clean_public_chat_body_broken_markdown_link(self):
        result = AiGroupChatService._clean_public_chat_body("[文字（不完整 内容")
        assert "文字" in result

    def test_clean_public_chat_body_relay_task_id(self):
        result = AiGroupChatService._clean_public_chat_body("内容；中继任务：abcdef0123456789。")
        assert "中继任务" not in result or result.endswith("。")

    def test_clean_public_chat_body_bold_token(self):
        result = AiGroupChatService._clean_public_chat_body("**加粗** 内容")
        assert "加粗" in result
        assert "**" not in result

    def test_clean_public_chat_body_underscore_token(self):
        result = AiGroupChatService._clean_public_chat_body("__下划线__ 内容")
        assert "下划线" in result
        assert "__" not in result

    def test_clean_public_chat_body_backtick_token(self):
        result = AiGroupChatService._clean_public_chat_body("`代码` 内容")
        assert "代码" in result
        assert "`" not in result

    def test_clean_public_chat_body_multiline(self):
        result = AiGroupChatService._clean_public_chat_body("第一行\n第二行\n第三行")
        assert "第一行" in result
        assert "第二行" in result

    def test_clean_public_chat_body_carriage_return(self):
        result = AiGroupChatService._clean_public_chat_body("第一行\r\n第二行\r第三行")
        assert "第一行" in result
        assert "第二行" in result

    def test_clean_public_chat_body_empty(self):
        assert AiGroupChatService._clean_public_chat_body("") == ""

    def test_clean_public_chat_body_none(self):
        assert AiGroupChatService._clean_public_chat_body(None) == ""


# ---------------------------------------------------------------------------
# _compact_public_acceptance_body
# ---------------------------------------------------------------------------


class TestCompactPublicAcceptanceBodyEdge:
    """_compact_public_acceptance_body 的补充分支覆盖。"""

    def test_compact_acceptance_body_full(self):
        body = (
            "【小C验收】这单已收口\n"
            "结论：可以验收（2/2 个负责人已完成）\n"
            "任务：做任务\n"
            "成员：\n"
            "- 小销（focus）：完成。摘要\n"
            "- 小服（focus）：完成。摘要\n"
            "风险：未发现阻塞。\n"
            "下一步：满意就继续派下一步"
        )
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "【小C验收】" in result
        assert "结论：" in result
        assert "任务：" in result
        assert "成员：" in result
        assert "风险：" in result

    def test_compact_acceptance_body_missing_title(self):
        body = "结论：可以验收\n任务：做任务"
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "【小C验收】" in result

    def test_compact_acceptance_body_missing_conclusion(self):
        body = "【小C验收】这单已收口\n任务：做任务"
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "【小C验收】" in result
        assert "结论：" not in result

    def test_compact_acceptance_body_missing_task(self):
        body = "【小C验收】这单已收口\n结论：可以验收"
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "【小C验收】" in result
        assert "任务：" not in result

    def test_compact_acceptance_body_missing_risk(self):
        body = "【小C验收】这单已收口\n结论：可以验收"
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "风险：" not in result

    def test_compact_acceptance_body_more_than_4_members(self):
        body = (
            "【小C验收】这单已收口\n"
            "结论：可以验收\n"
            + "\n".join(f"- 成员{i}：完成。摘要" for i in range(6))
        )
        result = AiGroupChatService._compact_public_acceptance_body(body)
        assert "成员0" in result
        assert "成员3" in result
        assert "成员4" not in result

    def test_compact_acceptance_body_empty(self):
        assert AiGroupChatService._compact_public_acceptance_body("") == ""

    def test_compact_acceptance_body_none(self):
        assert AiGroupChatService._compact_public_acceptance_body(None) == ""

    def test_compact_acceptance_body_only_whitespace(self):
        assert AiGroupChatService._compact_public_acceptance_body("   \n  \n  ") == ""


# ---------------------------------------------------------------------------
# _public_status_label
# ---------------------------------------------------------------------------


class TestPublicStatusLabelEdge:
    """_public_status_label 的补充分支覆盖。"""

    def test_public_status_label_completed(self):
        assert AiGroupChatService._public_status_label("completed") == "完成"

    def test_public_status_label_done(self):
        assert AiGroupChatService._public_status_label("done") == "完成"

    def test_public_status_label_failed(self):
        assert AiGroupChatService._public_status_label("failed") == "失败"

    def test_public_status_label_blocked(self):
        assert AiGroupChatService._public_status_label("blocked") == "阻塞"

    def test_public_status_label_cancelled(self):
        assert AiGroupChatService._public_status_label("cancelled") == "已取消"

    def test_public_status_label_unknown(self):
        assert AiGroupChatService._public_status_label("unknown") == "unknown"

    def test_public_status_label_empty(self):
        assert AiGroupChatService._public_status_label("") == "已回报"

    def test_public_status_label_none(self):
        assert AiGroupChatService._public_status_label(None) == "已回报"

    def test_public_status_label_uppercase(self):
        assert AiGroupChatService._public_status_label("COMPLETED") == "完成"

    def test_public_status_label_with_whitespace(self):
        assert AiGroupChatService._public_status_label("  completed  ") == "完成"


# ---------------------------------------------------------------------------
# _strip_label_from_body
# ---------------------------------------------------------------------------


class TestStripLabelFromBodyEdge:
    """_strip_label_from_body 的补充分支覆盖。"""

    def test_strip_label_with_label(self):
        result = AiGroupChatService._strip_label_from_body("【小C派单】任务内容", "【小C派单】")
        assert result == "任务内容"

    def test_strip_label_without_label(self):
        result = AiGroupChatService._strip_label_from_body("任务内容", "【小C派单】")
        assert result == "任务内容"

    def test_strip_label_empty_body(self):
        assert AiGroupChatService._strip_label_from_body("", "【小C派单】") == ""

    def test_strip_label_none_body(self):
        assert AiGroupChatService._strip_label_from_body(None, "【小C派单】") == ""

    def test_strip_label_multiline_takes_first_line(self):
        result = AiGroupChatService._strip_label_from_body(
            "【小C派单】第一行\n第二行", "【小C派单】"
        )
        assert result == "第一行"

    def test_strip_label_truncates_to_160(self):
        long_text = "【小C派单】" + "a" * 200
        result = AiGroupChatService._strip_label_from_body(long_text, "【小C派单】")
        assert len(result) <= 160

    def test_strip_label_empty_label(self):
        result = AiGroupChatService._strip_label_from_body("任务内容", "")
        assert result == "任务内容"

    def test_strip_label_whitespace_body(self):
        result = AiGroupChatService._strip_label_from_body("  【小C派单】任务  ", "【小C派单】")
        assert result == "任务"


# ---------------------------------------------------------------------------
# _report_relay_task_id
# ---------------------------------------------------------------------------


class TestReportRelayTaskIdEdge:
    """_report_relay_task_id 的补充分支覆盖。"""

    def test_report_relay_task_id_from_raw(self):
        row = {"payload": {"raw": {"task_id": "task-123"}}}
        assert AiGroupChatService._report_relay_task_id(row) == "task-123"

    def test_report_relay_task_id_from_payload(self):
        row = {"payload": {"task_id": "task-456"}}
        assert AiGroupChatService._report_relay_task_id(row) == "task-456"

    def test_report_relay_task_id_no_payload(self):
        row = {}
        assert AiGroupChatService._report_relay_task_id(row) == ""

    def test_report_relay_task_id_payload_not_dict(self):
        row = {"payload": "not-a-dict"}
        assert AiGroupChatService._report_relay_task_id(row) == ""

    def test_report_relay_task_id_raw_not_dict(self):
        row = {"payload": {"raw": "not-a-dict"}}
        assert AiGroupChatService._report_relay_task_id(row) == ""

    def test_report_relay_task_id_empty_task_id(self):
        row = {"payload": {"raw": {"task_id": ""}}}
        assert AiGroupChatService._report_relay_task_id(row) == ""

    def test_report_relay_task_id_none_task_id(self):
        row = {"payload": {"raw": {"task_id": None}}}
        assert AiGroupChatService._report_relay_task_id(row) == ""

    def test_report_relay_task_id_strips_whitespace(self):
        row = {"payload": {"raw": {"task_id": "  task-789  "}}}
        assert AiGroupChatService._report_relay_task_id(row) == "task-789"


# ---------------------------------------------------------------------------
# _format_work_acceptance_message
# ---------------------------------------------------------------------------


class TestFormatWorkAcceptanceMessageEdge:
    """_format_work_acceptance_message 的补充分支覆盖。"""

    def test_format_acceptance_all_ok(self):
        work_order = {
            "payload": {"task": "做任务", "branch_context": "main"},
            "body": "【小C派单】做任务",
        }
        final_reports = [
            {
                "sender_name": "小销",
                "status": "completed",
                "payload": {"assignment_focus": "前端", "summary": "完成了"},
            },
            {
                "sender_name": "小服",
                "status": "done",
                "payload": {"assignment_focus": "后端", "summary": "完成了"},
            },
        ]
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=2,
            total=2,
            all_ok=True,
        )
        assert "可以验收" in result
        assert "2/2" in result
        assert "做任务" in result
        assert "main" in result
        assert "小销" in result
        assert "小服" in result

    def test_format_acceptance_needs_review(self):
        work_order = {
            "payload": {"task": "做任务"},
            "body": "【小C派单】做任务",
        }
        final_reports = [
            {
                "sender_name": "小销",
                "status": "failed",
                "payload": {"assignment_focus": "", "summary": "失败了"},
            },
        ]
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=0,
            total=1,
            all_ok=False,
        )
        assert "需要复核" in result
        assert "0/1" in result
        assert "未完成" in result

    def test_format_acceptance_missing_task_in_payload(self):
        work_order = {
            "payload": {},
            "body": "【小C派单】从body提取的任务",
        }
        final_reports = []
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=0,
            total=0,
            all_ok=True,
        )
        assert "从body提取的任务" in result

    def test_format_acceptance_missing_task_everywhere(self):
        work_order = {
            "payload": {},
            "body": "",
        }
        final_reports = []
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=0,
            total=0,
            all_ok=True,
        )
        assert "【小C验收】" in result

    def test_format_acceptance_no_branch(self):
        work_order = {
            "payload": {"task": "做任务"},
            "body": "【小C派单】做任务",
        }
        final_reports = []
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=0,
            total=0,
            all_ok=True,
        )
        assert "分支：" not in result

    def test_format_acceptance_with_branch_in_branch_key(self):
        work_order = {
            "payload": {"task": "做任务", "branch": "feature-1"},
            "body": "【小C派单】做任务",
        }
        final_reports = []
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=0,
            total=0,
            all_ok=True,
        )
        assert "feature-1" in result

    def test_format_acceptance_member_without_focus(self):
        work_order = {
            "payload": {"task": "做任务"},
            "body": "【小C派单】做任务",
        }
        final_reports = [
            {
                "sender_name": "小销",
                "status": "completed",
                "payload": {"summary": "完成了"},
            },
        ]
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=1,
            total=1,
            all_ok=True,
        )
        assert "小销" in result
        assert "小销（" not in result  # 没有 focus 时不加括号

    def test_format_acceptance_member_with_empty_name(self):
        work_order = {
            "payload": {"task": "做任务"},
            "body": "【小C派单】做任务",
        }
        final_reports = [
            {
                "sender_name": "",
                "status": "completed",
                "payload": {"employee_name": "备用名", "summary": "完成了"},
            },
        ]
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=1,
            total=1,
            all_ok=True,
        )
        assert "备用名" in result

    def test_format_acceptance_truncates_to_6_members(self):
        work_order = {
            "payload": {"task": "做任务"},
            "body": "【小C派单】做任务",
        }
        final_reports = [
            {
                "sender_name": f"成员{i}",
                "status": "completed",
                "payload": {"summary": "完成了"},
            }
            for i in range(8)
        ]
        result = AiGroupChatService._format_work_acceptance_message(
            work_order=work_order,
            final_reports=final_reports,
            ok_count=8,
            total=8,
            all_ok=True,
        )
        assert "成员0" in result
        assert "成员5" in result
        assert "成员6" not in result


# ---------------------------------------------------------------------------
# _append_work_acceptance_if_ready
# ---------------------------------------------------------------------------


class TestAppendWorkAcceptanceIfReadyEdge:
    """_append_work_acceptance_if_ready 的补充分支覆盖。"""

    def test_append_acceptance_empty_work_order_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id=""
        )
        assert result is None

    def test_append_acceptance_no_rows(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is None

    def test_append_acceptance_already_exists(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # 先写入一条已存在的验收消息
        existing = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_acceptance",
            "work_order_id": "wo1",
            "status": "completed",
            "body": "已验收",
            "sender_name": "小C助理",
            "sender_id": "xcagi-assistant",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([existing])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is not None
        assert result["id"] == "msg1"

    def test_append_acceptance_no_work_order(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # 只有 work_report，没有 work_order
        report = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "completed",
            "body": "汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        svc._append_messages([report])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is None

    def test_append_acceptance_no_initial_reports(self, tmp_path: Path):
        svc = make_service(tmp_path)
        work_order = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_order",
            "work_order_id": "wo1",
            "status": "assigned",
            "body": "派单",
            "sender_name": "工作流调度",
            "sender_id": "ai-group-dispatcher",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"task": "做任务"},
        }
        svc._append_messages([work_order])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is None

    def test_append_acceptance_initial_reports_no_final(self, tmp_path: Path):
        svc = make_service(tmp_path)
        work_order = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_order",
            "work_order_id": "wo1",
            "status": "assigned",
            "body": "派单",
            "sender_name": "工作流调度",
            "sender_id": "ai-group-dispatcher",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"task": "做任务"},
        }
        report = {
            "id": "msg2",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "queued",
            "body": "汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:01+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        svc._append_messages([work_order, report])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is None

    def test_append_acceptance_final_reports_not_terminal(self, tmp_path: Path):
        svc = make_service(tmp_path)
        work_order = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_order",
            "work_order_id": "wo1",
            "status": "assigned",
            "body": "派单",
            "sender_name": "工作流调度",
            "sender_id": "ai-group-dispatcher",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"task": "做任务"},
        }
        report = {
            "id": "msg2",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "queued",
            "body": "汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:01+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        final = {
            "id": "msg3",
            "user_id": 1,
            "group_id": "g1",
            "kind": "relay_work_report",
            "work_order_id": "wo1",
            "status": "running",  # 非终态
            "body": "中继汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:02+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        svc._append_messages([work_order, report, final])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is None

    def test_append_acceptance_all_completed(self, tmp_path: Path):
        svc = make_service(tmp_path)
        work_order = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_order",
            "work_order_id": "wo1",
            "status": "assigned",
            "body": "派单",
            "sender_name": "工作流调度",
            "sender_id": "ai-group-dispatcher",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"task": "做任务", "branch_context": "main"},
        }
        report = {
            "id": "msg2",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "queued",
            "body": "汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:01+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        final = {
            "id": "msg3",
            "user_id": 1,
            "group_id": "g1",
            "kind": "relay_work_report",
            "work_order_id": "wo1",
            "status": "completed",
            "body": "中继汇报",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:02+00:00",
            "payload": {
                "raw": {"task_id": "task1"},
                "assignment_focus": "前端",
                "summary": "完成了",
            },
        }
        svc._append_messages([work_order, report, final])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is not None
        assert result["kind"] == "work_acceptance"
        assert result["status"] == "completed"

    def test_append_acceptance_some_failed(self, tmp_path: Path):
        svc = make_service(tmp_path)
        work_order = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_order",
            "work_order_id": "wo1",
            "status": "assigned",
            "body": "派单",
            "sender_name": "工作流调度",
            "sender_id": "ai-group-dispatcher",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {"task": "做任务"},
        }
        report1 = {
            "id": "msg2",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "queued",
            "body": "汇报1",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:01+00:00",
            "payload": {"raw": {"task_id": "task1"}},
        }
        report2 = {
            "id": "msg3",
            "user_id": 1,
            "group_id": "g1",
            "kind": "work_report",
            "work_order_id": "wo1",
            "status": "queued",
            "body": "汇报2",
            "sender_name": "小服",
            "sender_id": "e2",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:02+00:00",
            "payload": {"raw": {"task_id": "task2"}},
        }
        final1 = {
            "id": "msg4",
            "user_id": 1,
            "group_id": "g1",
            "kind": "relay_work_report",
            "work_order_id": "wo1",
            "status": "completed",
            "body": "中继汇报1",
            "sender_name": "小销",
            "sender_id": "e1",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:03+00:00",
            "payload": {"raw": {"task_id": "task1"}, "summary": "完成了"},
        }
        final2 = {
            "id": "msg5",
            "user_id": 1,
            "group_id": "g1",
            "kind": "relay_work_report",
            "work_order_id": "wo1",
            "status": "failed",
            "body": "中继汇报2",
            "sender_name": "小服",
            "sender_id": "e2",
            "role": "ai",
            "sender_avatar": "",
            "created_at": "2026-01-01T00:00:04+00:00",
            "payload": {"raw": {"task_id": "task2"}, "summary": "失败了"},
        }
        svc._append_messages([work_order, report1, report2, final1, final2])
        result = svc._append_work_acceptance_if_ready(
            user_id=1, group_id="g1", work_order_id="wo1"
        )
        assert result is not None
        assert result["status"] == "needs_review"


# ---------------------------------------------------------------------------
# _normalize_branch_context
# ---------------------------------------------------------------------------


class TestNormalizeBranchContextEdge:
    """_normalize_branch_context 的补充分支覆盖。"""

    def test_normalize_branch_empty(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context("") == ""

    def test_normalize_branch_none(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context(None) == ""

    def test_normalize_branch_origin_prefix(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context("origin/main") == "main"

    def test_normalize_branch_special_chars(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context("feature@branch#test")
        assert "@" not in result
        assert "#" not in result

    def test_normalize_branch_spaces_replaced(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context("feature branch")
        assert " " not in result
        assert "-" in result

    def test_normalize_branch_multiple_slashes(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context("feature//branch")
        assert "//" not in result

    def test_normalize_branch_double_dot(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context("feature..branch")
        assert ".." not in result

    def test_normalize_branch_head_returns_empty(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context("HEAD") == ""

    def test_normalize_branch_dot_returns_empty(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context(".") == ""

    def test_normalize_branch_double_dot_only_returns_empty(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context("..") == ""

    def test_normalize_branch_truncates_to_180(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        long_branch = "a" * 200
        result = _normalize_branch_context(long_branch)
        assert len(result) <= 180

    def test_normalize_branch_strips_leading_trailing_slash(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context("/feature/")
        assert not result.startswith("/")
        assert not result.endswith("/")

    def test_normalize_branch_strips_leading_trailing_dot(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        result = _normalize_branch_context(".feature.")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_normalize_branch_normal(self):
        from app.application.ai_group_chat_service import _normalize_branch_context
        assert _normalize_branch_context("feature/branch-1") == "feature/branch-1"


# ---------------------------------------------------------------------------
# delete_message
# ---------------------------------------------------------------------------


class TestDeleteMessageEdge:
    """delete_message 的补充分支覆盖。"""

    def test_delete_message_empty_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id="")

    def test_delete_message_none_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id=None)

    def test_delete_message_whitespace_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id="   ")

    def test_delete_message_not_found(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id="nonexistent")

    def test_delete_message_wrong_user(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg = {
            "id": "msg1",
            "user_id": 2,  # 不同用户
            "group_id": "g1",
            "role": "user",
            "sender_id": "user",
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([msg])
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id="msg1")

    def test_delete_message_wrong_group(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g2",  # 不同群
            "role": "user",
            "sender_id": "user",
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([msg])
        with pytest.raises(ValueError, match="消息不存在"):
            svc.delete_message(user_id=1, group_id="g1", message_id="msg1")

    def test_delete_message_ai_message_not_allowed(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "role": "ai",  # AI 消息
            "sender_id": "e1",
            "sender_name": "小销",
            "sender_avatar": "",
            "body": "消息",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([msg])
        with pytest.raises(ValueError, match="只能删除自己发送的消息"):
            svc.delete_message(user_id=1, group_id="g1", message_id="msg1")

    def test_delete_message_wrong_sender_not_allowed(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "role": "user",
            "sender_id": "other",  # 非 user
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([msg])
        with pytest.raises(ValueError, match="只能删除自己发送的消息"):
            svc.delete_message(user_id=1, group_id="g1", message_id="msg1")

    def test_delete_message_success(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "role": "user",
            "sender_id": "user",
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc._append_messages([msg])
        result = svc.delete_message(user_id=1, group_id="g1", message_id="msg1")
        assert result == {"deleted": True, "id": "msg1"}
        # 验证消息已被删除
        messages = svc._read_messages()
        assert len(messages) == 0

    def test_delete_message_only_deletes_target(self, tmp_path: Path):
        svc = make_service(tmp_path)
        msg1 = {
            "id": "msg1",
            "user_id": 1,
            "group_id": "g1",
            "role": "user",
            "sender_id": "user",
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息1",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        msg2 = {
            "id": "msg2",
            "user_id": 1,
            "group_id": "g1",
            "role": "user",
            "sender_id": "user",
            "sender_name": "我",
            "sender_avatar": "",
            "body": "消息2",
            "created_at": "2026-01-01T00:00:01+00:00",
        }
        svc._append_messages([msg1, msg2])
        result = svc.delete_message(user_id=1, group_id="g1", message_id="msg1")
        assert result == {"deleted": True, "id": "msg1"}
        messages = svc._read_messages()
        assert len(messages) == 1
        assert messages[0]["id"] == "msg2"


# ---------------------------------------------------------------------------
# _format_work_report_message 补充分支
# ---------------------------------------------------------------------------


class TestFormatWorkReportMessageExtraEdge:
    """_format_work_report_message 的补充分支覆盖。"""

    def test_work_report_queued_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "queued", "summary": "已接单", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result
        assert "我完成后会自动回到群里汇报" in result

    def test_work_report_accepted_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "accepted", "summary": "已接单"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result

    def test_work_report_assigned_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "assigned", "summary": "已接单"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result

    def test_work_report_running_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "running", "summary": "执行中"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "执行中" in result

    def test_work_report_in_progress_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "in_progress", "summary": "执行中"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "执行中" in result

    def test_work_report_blocked_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "blocked", "summary": "阻塞了"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "阻塞" in result

    def test_work_report_unknown_status_success(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "custom_status", "summary": "完成了"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "完成" in result

    def test_work_report_unknown_status_failed(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "custom_status", "summary": "失败了"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "失败" in result

    def test_work_report_with_focus(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {
            "success": True,
            "status": "done",
            "summary": "完成了",
            "assignment_focus": "前端开发",
        }
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "前端开发" in result

    def test_work_report_with_branch(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {
            "success": True,
            "status": "done",
            "summary": "完成了",
            "branch_context": "feature-1",
        }
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "feature-1" in result

    def test_work_report_with_branch_key(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {
            "success": True,
            "status": "done",
            "summary": "完成了",
            "branch": "feature-2",
        }
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "feature-2" in result

    def test_work_report_empty_summary(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "done", "summary": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "无结果摘要" in result

    def test_work_report_empty_risk_success(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "done", "summary": "完成了", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "未发现阻塞" in result

    def test_work_report_empty_risk_failed(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "failed", "summary": "失败了", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "存在执行阻塞" in result

    def test_work_report_no_member_name(self):
        member = {"employee_id": "e1"}
        report = {"success": True, "status": "done", "summary": "完成了"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "e1" in result

    def test_work_report_no_member_employee_id(self):
        member = {}
        report = {"success": True, "status": "done", "summary": "完成了"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "员工" in result


# ---------------------------------------------------------------------------
# _format_work_order_message 补充分支
# ---------------------------------------------------------------------------


class TestFormatWorkOrderMessageExtraEdge:
    """_format_work_order_message 的补充分支覆盖。"""

    def test_work_order_with_assignments(self):
        assignments = [
            {"name": "小销", "employee_id": "e1", "assignment_focus": "前端"},
            {"name": "小服", "employee_id": "e2", "assignment_focus": "后端"},
        ]
        result = AiGroupChatService._format_work_order_message(
            "做任务", ["小销", "小服"], assignments=assignments
        )
        assert "分工：" in result
        assert "小销：前端" in result
        assert "小服：后端" in result

    def test_work_order_with_main_responsible_assignments(self):
        assignments = [
            {"name": "小销", "employee_id": "e1", "assignment_focus": "主负责人"},
        ]
        result = AiGroupChatService._format_work_order_message(
            "做任务", ["小销"], assignments=assignments
        )
        assert "分工：" not in result  # 主负责人不显示分工

    def test_work_order_with_branch_context(self):
        result = AiGroupChatService._format_work_order_message(
            "做任务", ["小销"], branch_context="feature-1"
        )
        assert "feature-1" in result

    def test_work_order_no_branch_context(self):
        result = AiGroupChatService._format_work_order_message("做任务", ["小销"])
        assert "自动隔离分支" in result

    def test_work_order_empty_assignment_name(self):
        assignments = [
            {"name": "", "employee_id": "e1", "assignment_focus": "前端"},
        ]
        result = AiGroupChatService._format_work_order_message(
            "做任务", [""], assignments=assignments
        )
        assert "e1：前端" in result

    def test_work_order_assignment_no_focus(self):
        assignments = [
            {"name": "小销", "employee_id": "e1", "assignment_focus": ""},
        ]
        result = AiGroupChatService._format_work_order_message(
            "做任务", ["小销"], assignments=assignments
        )
        assert "分工：" not in result


# ---------------------------------------------------------------------------
# _relay_result_summary 补充分支
# ---------------------------------------------------------------------------


class TestRelayResultSummaryExtraEdge:
    """_relay_result_summary 的补充分支覆盖。"""

    def test_relay_summary_from_summary(self):
        result = AiGroupChatService._relay_result_summary(
            {"summary": "摘要内容"}, "completed", "task1"
        )
        assert "摘要内容" in result

    def test_relay_summary_from_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"message": "消息内容"}, "completed", "task1"
        )
        assert "消息内容" in result

    def test_relay_summary_from_output(self):
        result = AiGroupChatService._relay_result_summary(
            {"output": "输出内容"}, "completed", "task1"
        )
        assert "输出内容" in result

    def test_relay_summary_from_report(self):
        result = AiGroupChatService._relay_result_summary(
            {"report": "报告内容"}, "completed", "task1"
        )
        assert "报告内容" in result

    def test_relay_summary_from_error(self):
        result = AiGroupChatService._relay_result_summary(
            {"error": "错误内容"}, "failed", "task1"
        )
        assert "错误内容" in result

    def test_relay_summary_from_nested_assistant_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"data": {"assistant_message": {"body": "助手消息"}}},
            "completed",
            "task1",
        )
        assert "助手消息" in result

    def test_relay_summary_from_nested_summary(self):
        result = AiGroupChatService._relay_result_summary(
            {"data": {"summary": "嵌套摘要"}}, "completed", "task1"
        )
        assert "嵌套摘要" in result

    def test_relay_summary_from_nested_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"data": {"message": "嵌套消息"}}, "completed", "task1"
        )
        assert "嵌套消息" in result

    def test_relay_summary_no_candidates_returns_default(self):
        result = AiGroupChatService._relay_result_summary({}, "completed", "task1")
        assert "task1" in result
        assert "completed" in result

    def test_relay_summary_empty_status(self):
        result = AiGroupChatService._relay_result_summary({}, "", "task1")
        assert "task1" in result


# ---------------------------------------------------------------------------
# _relay_result_risk 补充分支
# ---------------------------------------------------------------------------


class TestRelayResultRiskExtraEdge:
    """_relay_result_risk 的补充分支覆盖。"""

    def test_relay_risk_from_risk(self):
        result = AiGroupChatService._relay_result_risk(
            result={"risk": "风险内容"},
            success=True,
            task_id="task1",
            dispatcher="dispatcher1",
        )
        assert result == "风险内容"

    def test_relay_risk_from_error(self):
        result = AiGroupChatService._relay_result_risk(
            result={"error": "错误风险"},
            success=False,
            task_id="task1",
            dispatcher="",
        )
        assert result == "错误风险"

    def test_relay_risk_from_reason(self):
        result = AiGroupChatService._relay_result_risk(
            result={"reason": "原因风险"},
            success=False,
            task_id="task1",
            dispatcher="",
        )
        assert result == "原因风险"

    def test_relay_risk_success_no_explicit_risk(self):
        result = AiGroupChatService._relay_result_risk(
            result={},
            success=True,
            task_id="task1",
            dispatcher="dispatcher1",
        )
        assert "未发现阻塞" in result
        assert "dispatcher1" in result
        assert "task1" in result

    def test_relay_risk_failed_no_explicit_risk(self):
        result = AiGroupChatService._relay_result_risk(
            result={},
            success=False,
            task_id="task1",
            dispatcher="dispatcher1",
        )
        assert "未成功完成" in result
        assert "dispatcher1" in result
        assert "task1" in result

    def test_relay_risk_no_dispatcher_no_task_id(self):
        result = AiGroupChatService._relay_result_risk(
            result={},
            success=True,
            task_id="",
            dispatcher="",
        )
        assert "未发现阻塞" in result
        assert "执行端" not in result
        assert "中继任务" not in result

    def test_relay_risk_truncates_to_500(self):
        long_risk = "a" * 600
        result = AiGroupChatService._relay_result_risk(
            result={"risk": long_risk},
            success=True,
            task_id="task1",
            dispatcher="",
        )
        assert len(result) <= 500


# ---------------------------------------------------------------------------
# _execution_summary 补充分支
# ---------------------------------------------------------------------------


class TestExecutionSummaryExtraEdge:
    """_execution_summary 的补充分支覆盖。"""

    def test_execution_summary_from_summary(self):
        result = AiGroupChatService._execution_summary({"summary": "摘要"})
        assert result == "摘要"

    def test_execution_summary_from_message(self):
        result = AiGroupChatService._execution_summary({"message": "消息"})
        assert result == "消息"

    def test_execution_summary_from_output(self):
        result = AiGroupChatService._execution_summary({"output": "输出"})
        assert result == "输出"

    def test_execution_summary_from_result(self):
        result = AiGroupChatService._execution_summary({"result": "结果"})
        assert result == "结果"

    def test_execution_summary_from_report(self):
        result = AiGroupChatService._execution_summary({"report": "报告"})
        assert result == "报告"

    def test_execution_summary_from_data_dict(self):
        result = AiGroupChatService._execution_summary(
            {"data": {"summary": "数据摘要"}}
        )
        assert result == "数据摘要"

    def test_execution_summary_from_data_dict_message(self):
        result = AiGroupChatService._execution_summary(
            {"data": {"message": "数据消息"}}
        )
        assert result == "数据消息"

    def test_execution_summary_no_candidates_returns_stringified(self):
        result = AiGroupChatService._execution_summary({"custom": "value"})
        assert "value" in result

    def test_execution_summary_truncates_to_1200(self):
        long_summary = "a" * 2000
        result = AiGroupChatService._execution_summary({"summary": long_summary})
        assert len(result) <= 1200

    def test_execution_summary_from_data_truncates_to_1200(self):
        long_summary = "a" * 2000
        result = AiGroupChatService._execution_summary(
            {"data": {"summary": long_summary}}
        )
        assert len(result) <= 1200


# ---------------------------------------------------------------------------
# _execution_risk 补充分支
# ---------------------------------------------------------------------------


class TestExecutionRiskExtraEdge:
    """_execution_risk 的补充分支覆盖。"""

    def test_execution_risk_from_risk(self):
        result = AiGroupChatService._execution_risk({"risk": "风险"}, True)
        assert result == "风险"

    def test_execution_risk_from_risks(self):
        result = AiGroupChatService._execution_risk({"risks": "风险s"}, True)
        assert result == "风险s"

    def test_execution_risk_from_blocker(self):
        result = AiGroupChatService._execution_risk({"blocker": "阻塞"}, False)
        assert result == "阻塞"

    def test_execution_risk_from_data_risk(self):
        result = AiGroupChatService._execution_risk({"data": {"risk": "数据风险"}}, True)
        assert result == "数据风险"

    def test_execution_risk_from_data_risks(self):
        result = AiGroupChatService._execution_risk({"data": {"risks": "数据风险s"}}, True)
        assert result == "数据风险s"

    def test_execution_risk_from_data_blocker(self):
        result = AiGroupChatService._execution_risk({"data": {"blocker": "数据阻塞"}}, False)
        assert result == "数据阻塞"

    def test_execution_risk_success_no_explicit(self):
        result = AiGroupChatService._execution_risk({}, True)
        assert "未发现阻塞" in result

    def test_execution_risk_failed_no_explicit(self):
        result = AiGroupChatService._execution_risk({}, False)
        assert "执行失败" in result

    def test_execution_risk_truncates_to_500(self):
        long_risk = "a" * 600
        result = AiGroupChatService._execution_risk({"risk": long_risk}, True)
        assert len(result) <= 500


# ---------------------------------------------------------------------------
# _stringify_summary 补充分支
# ---------------------------------------------------------------------------


class TestStringifySummaryExtraEdge:
    """_stringify_summary 的补充分支覆盖。"""

    def test_stringify_none(self):
        assert AiGroupChatService._stringify_summary(None) == ""

    def test_stringify_string(self):
        assert AiGroupChatService._stringify_summary("  text  ") == "text"

    def test_stringify_dict(self):
        result = AiGroupChatService._stringify_summary({"a": 1})
        assert "a" in result
        assert "1" in result

    def test_stringify_list(self):
        result = AiGroupChatService._stringify_summary([1, 2, 3])
        assert "1" in result

    def test_stringify_int(self):
        result = AiGroupChatService._stringify_summary(42)
        assert "42" in result

    def test_stringify_float(self):
        result = AiGroupChatService._stringify_summary(3.14)
        assert "3.14" in result

    def test_stringify_bool(self):
        result = AiGroupChatService._stringify_summary(True)
        assert "true" in result

    def test_stringify_truncates_to_1200(self):
        long_data = {"data": "a" * 2000}
        result = AiGroupChatService._stringify_summary(long_data)
        assert len(result) <= 1200

    def test_stringify_object_with_typeerror(self):
        class Unserializable:
            def __init__(self):
                self.x = self  # 循环引用

        result = AiGroupChatService._stringify_summary(Unserializable())
        assert len(result) > 0  # 回退到 str()


# ---------------------------------------------------------------------------
# _compact_result 补充分支
# ---------------------------------------------------------------------------


class TestCompactResultExtraEdge:
    """_compact_result 的补充分支覆盖。"""

    def test_compact_result_empty(self):
        result = AiGroupChatService._compact_result({})
        assert result == {}

    def test_compact_result_all_keys(self):
        result = AiGroupChatService._compact_result({
            "success": True,
            "status": "done",
            "message": "msg",
            "summary": "sum",
            "task_id": "t1",
            "run_id": "r1",
            "error": "err",
            "dispatch_request_id": "dr1",
            "dispatcher": "disp",
            "relay_id": "rel1",
        })
        assert result["success"] is True
        assert result["status"] == "done"
        assert result["message"] == "msg"
        assert result["summary"] == "sum"
        assert result["task_id"] == "t1"
        assert result["run_id"] == "r1"
        assert result["error"] == "err"
        assert result["dispatch_request_id"] == "dr1"
        assert result["dispatcher"] == "disp"
        assert result["relay_id"] == "rel1"

    def test_compact_result_none_values(self):
        result = AiGroupChatService._compact_result({
            "success": None,
            "status": None,
            "message": None,
        })
        assert result["success"] is None
        assert result["status"] is None
        assert result["message"] is None

    def test_compact_result_complex_values_stringified(self):
        result = AiGroupChatService._compact_result({
            "summary": {"nested": "dict"},
            "message": ["list", "value"],
        })
        assert isinstance(result["summary"], str)
        assert isinstance(result["message"], str)

    def test_compact_result_ignores_unknown_keys(self):
        result = AiGroupChatService._compact_result({
            "unknown_key": "value",
            "success": True,
        })
        assert "unknown_key" not in result
        assert result["success"] is True

    def test_compact_result_int_and_float(self):
        result = AiGroupChatService._compact_result({
            "task_id": 123,
            "run_id": 4.56,
        })
        assert result["task_id"] == 123
        assert result["run_id"] == 4.56

    def test_compact_result_bool(self):
        result = AiGroupChatService._compact_result({
            "success": True,
        })
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _relay_result_dispatch_value 补充分支
# ---------------------------------------------------------------------------


class TestRelayResultDispatchValueExtraEdge:
    """_relay_result_dispatch_value 的补充分支覆盖。"""

    def test_dispatch_value_finds_key(self):
        result = {
            "data": {"dispatch": {"status": "queued", "request_id": "req1"}},
        }
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == "queued"
        assert AiGroupChatService._relay_result_dispatch_value(result, "request_id") == "req1"

    def test_dispatch_value_no_dict_values(self):
        result = {"key": "string_value"}
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == ""

    def test_dispatch_value_no_dispatch_in_dict(self):
        result = {"data": {"other": "value"}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == ""

    def test_dispatch_value_dispatch_not_dict(self):
        result = {"data": {"dispatch": "not-a-dict"}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == ""

    def test_dispatch_value_key_is_none(self):
        result = {"data": {"dispatch": {"status": None}}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == ""

    def test_dispatch_value_multiple_dicts(self):
        result = {
            "first": {"dispatch": {"status": "first_status"}},
            "second": {"dispatch": {"status": "second_status"}},
        }
        # 返回第一个找到的
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == "first_status"

    def test_dispatch_value_empty_result(self):
        assert AiGroupChatService._relay_result_dispatch_value({}, "status") == ""


# ---------------------------------------------------------------------------
# _latest_relay_desktop 补充分支
# ---------------------------------------------------------------------------


class TestLatestRelayDesktopExtraEdge:
    """_latest_relay_desktop 的补充分支覆盖。"""

    def test_latest_relay_desktop_empty_list(self):
        assert AiGroupChatService._latest_relay_desktop([]) is None

    def test_latest_relay_desktop_no_paired(self):
        desktops = [
            {"relay_id": "r1", "status": "offline"},
            {"relay_id": "r2", "status": "pending"},
        ]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_no_relay_id(self):
        desktops = [
            {"status": "paired"},  # 无 relay_id
        ]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_empty_relay_id(self):
        desktops = [
            {"relay_id": "", "status": "paired"},
        ]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_single_paired(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r1"

    def test_latest_relay_desktop_multiple_paired_returns_latest(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "last_seen_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_updated_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "updated_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "updated_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_paired_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "paired_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "paired_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_created_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "created_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "created_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_filters_non_dict(self):
        desktops = [
            "not-a-dict",
            {"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r1"

    def test_latest_relay_desktop_mixed_statuses(self):
        desktops = [
            {"relay_id": "r1", "status": "offline", "last_seen_at": "2026-01-03"},
            {"relay_id": "r2", "status": "paired", "last_seen_at": "2026-01-01"},
            {"relay_id": "r3", "status": "paired", "last_seen_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r3"

    def test_latest_relay_desktop_uppercase_paired(self):
        desktops = [
            {"relay_id": "r1", "status": "PAIRED", "last_seen_at": "2026-01-01"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r1"
