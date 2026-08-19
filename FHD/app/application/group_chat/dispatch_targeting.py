"""Dispatch target selection and assignment formatting."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.application.group_chat.constants import (
    _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
    _SUPER_EMPLOYEE_IDS,
    MAX_RESPONDERS,
)


class DispatchTargetingMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    @staticmethod
    def _parse_routing_json(
        content: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[str], str]:
        text = (content or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return [], ""
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return [], ""
        valid_ids = {str(m.get("employee_id") or "") for m in candidates}
        raw_ids = data.get("target_employee_ids")
        if not isinstance(raw_ids, list):
            raw_ids = data.get("targets")
        target_ids = [
            str(item).strip()
            for item in (raw_ids if isinstance(raw_ids, list) else [])
            if str(item).strip() in valid_ids
        ]
        rationale = str(data.get("rationale") or data.get("reason") or "").strip()
        return target_ids[:MAX_RESPONDERS], rationale[:500]

    @staticmethod
    def _heuristic_dispatch_targets(
        candidates: list[dict[str, Any]],
        task: str,
    ) -> list[dict[str, Any]]:
        by_id = {str(m.get("employee_id") or ""): m for m in candidates}
        text = (task or "").lower()
        if DispatchTargetingMixin._dispatch_difficulty(task) == "simple":
            preferred = DispatchTargetingMixin._preferred_single_dispatch_target(candidates, task)
            return [preferred] if preferred else []
        wanted: list[str] = []
        if any(
            k in text
            for k in (
                "android",
                "移动端",
                "手机",
                "compose",
                "kotlin",
                "页面",
                "输入框",
                "样式",
                "ui",
                "ux",
                "体验",
                "头像",
                "语音",
            )
        ):
            wanted.append("cursor-super-employee")
        if any(
            k in text
            for k in (
                "后端",
                "接口",
                "api",
                "pytest",
                "测试",
                "覆盖",
                "服务",
                "python",
                "修复",
                "实现",
            )
        ):
            wanted.append("codex-super-employee")
        if any(
            k in text
            for k in (
                "架构",
                "方案",
                "评审",
                "验收",
                "acceptance",
                "summary",
                "汇总",
                "规划",
                "路由",
                "分流",
                "链路",
            )
        ):
            wanted.append("claude-super-employee")
        if any(k in text for k in ("trae", "ide", "备用", "额度", "模型", "执行端")):
            wanted.append("trae-super-employee")
        selected = [by_id[eid] for eid in wanted if eid in by_id]
        if selected:
            return selected[:MAX_RESPONDERS]
        preferred = DispatchTargetingMixin._preferred_single_dispatch_target(candidates, task)
        return [preferred] if preferred else []

    @staticmethod
    def _dispatch_difficulty(task: str) -> str:
        text = (task or "").lower()
        simple_markers = (
            "简单",
            "小bug",
            "小 bug",
            "复制",
            "删除",
            "长按",
            "样式",
            "文案",
            "小问题",
        )
        large_markers = (
            "全链路",
            "整套",
            "架构",
            "重构",
            "多端",
            "大规模",
            "全部",
            "多个模块",
            "一起工作",
            "并行",
        )
        if any(k in text for k in large_markers):
            return "large"
        if any(k in text for k in simple_markers) or len(text) <= 90:
            return "simple"
        return "medium"

    @staticmethod
    def _preferred_single_dispatch_target(
        candidates: list[dict[str, Any]],
        task: str,
    ) -> dict[str, Any] | None:
        if not candidates:
            return None
        by_id = {str(m.get("employee_id") or ""): m for m in candidates}
        text = (task or "").lower()
        dev_markers = (
            "后端",
            "接口",
            "api",
            "pytest",
            "测试",
            "test",
            "tests",
            "changed files",
            "命令",
            "服务",
            "python",
            "代码",
            "修复",
            "实现",
            "开发",
            "添加",
            "新增",
            "更新",
            "合并",
        )
        review_markers = ("架构", "方案", "评审", "验收", "规划", "路由", "分流")
        ui_markers = (
            "android",
            "移动端",
            "手机",
            "compose",
            "kotlin",
            "页面",
            "样式",
            "ui",
            "ux",
            "体验",
        )
        has_dev_work = any(k in text for k in dev_markers)
        if any(k in text for k in review_markers) and not has_dev_work:
            priority = [
                "claude-super-employee",
                _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
                "cursor-super-employee",
            ]
        elif any(k in text for k in ui_markers) and not has_dev_work:
            priority = [
                "cursor-super-employee",
                _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
                "claude-super-employee",
            ]
        else:
            priority = [
                _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
                "cursor-super-employee",
                "claude-super-employee",
                "trae-super-employee",
            ]
        for employee_id in priority:
            if employee_id in by_id:
                return by_id[employee_id]
        return next(
            (m for m in candidates if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS),
            candidates[0],
        )

    @staticmethod
    def _format_routing_decision_message(target_names: str, rationale: str) -> str:
        if not target_names:
            return (
                f"【小C分工】这单暂时没有找到可执行负责人。\n原因：{rationale or '候选员工为空。'}"
            )
        is_single = (
            "、" not in target_names and "," not in target_names and "，" not in target_names
        )
        intro = "这单先不拆，派一个负责人推进。" if is_single else "我先按职责拆给对应负责人。"
        return (
            f"【小C分工】{intro}\n"
            f"负责人：{target_names}\n"
            f"分工依据：{rationale or '按任务类型和成员能力分流。'}\n"
            "我会等大家回报后给你一条验收结论。"
        )

    def _build_dispatch_assignments(
        self,
        task: str,
        members: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        super_members = [
            m for m in members if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ]
        should_split = len(super_members) >= 2 and len(super_members) == len(members)
        assignments: list[dict[str, Any]] = []
        for member in members:
            assigned = dict(member)
            employee_id = str(member.get("employee_id") or "")
            if should_split:
                focus = self._super_employee_focus(employee_id, task)
                assigned["assignment_focus"] = focus
                assigned["assigned_task"] = self._format_assigned_task(
                    original_task=task,
                    employee_id=employee_id,
                    focus=focus,
                )
            else:
                assigned["assignment_focus"] = "主负责人"
                assigned["assigned_task"] = task
            assignments.append(assigned)
        return assignments

    @staticmethod
    def _super_employee_focus(employee_id: str, task: str) -> str:
        text = (task or "").lower()
        if employee_id == "cursor-super-employee":
            return "移动端体验、前端交互和可见 UI 验证"
        if employee_id == "codex-super-employee":
            return "服务端链路、数据状态、接口和自动化测试证据"
        if employee_id == "claude-super-employee":
            return "方案拆解、风险评审、验收标准和最终收口"
        if employee_id == "trae-super-employee":
            return "Trae 执行端、IDE 自动化、备用模型额度和补位执行"
        if "测试" in text or "验收" in text:
            return "按岗位职责完成验收相关部分"
        return "按岗位职责处理"

    @staticmethod
    def _format_assigned_task(*, original_task: str, employee_id: str, focus: str) -> str:
        boundary = {
            "cursor-super-employee": "只负责移动端/前端体验相关判断，不重复做后端日志核查。",
            "codex-super-employee": "只负责服务端/接口/测试证据，不重复做 UI 体验评价。",
            "claude-super-employee": "只负责验收口径、风险和团队收口，不重复实现或跑同一套检查。",
            "trae-super-employee": "只负责 Trae 执行端、IDE 自动化和备用执行，不重复做其它成员已负责的部分。",
        }.get(employee_id, "只处理自己职责范围内的部分。")
        return (
            f"子任务：{focus}。\n"
            f"原始需求：{original_task}\n"
            f"边界：{boundary}\n"
            "输出要求：只汇报你的职责结论、风险和下一步，不要代替其他成员完成同一部分。"
        )
