"""Dispatch / routing mixin for AiGroupChatDispatchMixin."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from app.application.group_chat.constants import (
    _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
    _SUPER_EMPLOYEE_IDS,
    _XIAOC_ASSISTANT_ID,
    CONTEXT_TURNS,
    MAX_RESPONDERS,
    SUPER_DISCUSSION_DEFAULT_ROUNDS,
    SUPER_DISCUSSION_MAX_ROUNDS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC as _DEFAULT_DISCUSSION_COMPLETION_TIMEOUT_SEC,
)
from app.application.group_chat.employee_registry import _is_required_group_member


def _discussion_completion_timeout_sec() -> float:
    """Honor the legacy module-level timeout override after the service split."""
    from app.application import ai_group_chat_service as compatibility_module

    return float(
        getattr(
            compatibility_module,
            "SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC",
            _DEFAULT_DISCUSSION_COMPLETION_TIMEOUT_SEC,
        )
    )


class AiGroupChatDispatchMixin:
    # ── 回复编排 ──

    def _pick_responders(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        if self._is_broadcast_mention(text):
            return members[:MAX_RESPONDERS]
        explicit = self._explicit_member_ids(members, text, mentions)
        if explicit:
            targeted = [m for m in members if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        xiaoc = next(
            (m for m in members if str(m.get("employee_id") or "") == _XIAOC_ASSISTANT_ID),
            None,
        )
        # 真实工作群默认不会全员接话：先由小C接待，点名/广播才拉对应员工响应。
        return [xiaoc or members[0]]

    def _pick_dispatch_targets(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        work_capable = [
            m for m in members if not _is_required_group_member(str(m.get("employee_id") or ""))
        ]
        if self._mode != "admin":
            # 超级员工仅管理端可派工：企业端即便历史已入群也不会被选为派工对象。
            work_capable = [
                m
                for m in work_capable
                if str(m.get("employee_id") or "") not in _SUPER_EMPLOYEE_IDS
            ]
        if not work_capable:
            return []
        if self._is_broadcast_mention(text):
            return work_capable[:MAX_RESPONDERS]
        explicit = self._explicit_member_ids(members, text, mentions)
        if explicit:
            targeted = [m for m in work_capable if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        return work_capable[:MAX_RESPONDERS]

    def _explicit_member_ids(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> set[str]:
        explicit = {str(m).strip() for m in (mentions or []) if str(m).strip()}
        for member in members:
            employee_id = str(member.get("employee_id") or "").strip()
            name = str(member.get("name") or "").strip()
            if name and f"@{name}" in text:
                explicit.add(employee_id)
            if employee_id and f"@{employee_id}" in text:
                explicit.add(employee_id)
        return explicit

    @staticmethod
    def _is_broadcast_mention(text: str) -> bool:
        lower = (text or "").lower()
        return any(marker in lower for marker in ("@所有人", "@全体", "@全员", "@all", "@everyone"))

    @staticmethod
    def _should_run_super_discussion(members: list[dict[str, Any]]) -> bool:
        super_count = sum(
            1 for m in members if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        )
        return super_count >= 2

    async def _run_super_discussion_then_route(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        user_id: int,
        history: list[dict[str, Any]],
        mentions: list[str] | None,
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        super_members = [
            m for m in candidates if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ][:3]
        discussion_rows: list[dict[str, Any]] = []
        discussion_turns: list[dict[str, str]] = []
        rounds = self._discussion_round_count()
        assessment = self._xiaoc_dispatch_assessment(task=task, candidates=candidates)
        discussion_turns.append(
            {
                "employee_id": _XIAOC_ASSISTANT_ID,
                "name": "小C助理",
                "body": assessment,
                "round": "0",
            }
        )
        assessment_row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=assessment,
            kind="discussion",
            status="completed",
            payload={
                "round": 0,
                "task": task,
                "phase": "pre_dispatch_assessment",
                "difficulty": self._dispatch_difficulty(task),
            },
        )
        discussion_rows.append(assessment_row)
        if persist:
            self._append_messages([assessment_row])
        for round_index in range(1, rounds + 1):
            for member in super_members:
                content = await self._super_discussion_reply(
                    group=group,
                    member=member,
                    task=task,
                    history=history,
                    discussion_turns=discussion_turns,
                    round_index=round_index,
                )
                turn = {
                    "employee_id": str(member.get("employee_id") or ""),
                    "name": str(member.get("name") or member.get("employee_id") or ""),
                    "body": content,
                    "round": str(round_index),
                }
                discussion_turns.append(turn)
                row = self._message_row(
                    user_id=user_id,
                    group_id=group_id,
                    role="ai",
                    sender_id=turn["employee_id"],
                    sender_name=turn["name"],
                    sender_avatar=str(member.get("avatar") or ""),
                    body=content,
                    kind="discussion",
                    status="completed",
                    payload={"round": round_index, "task": task, "phase": "pre_dispatch"},
                )
                discussion_rows.append(row)
                if persist:
                    self._append_messages([row])

        selected, rationale = await self._route_after_discussion(
            group=group,
            task=task,
            candidates=candidates,
            discussion_turns=discussion_turns,
            mentions=mentions,
        )
        selected_names = "、".join(
            str(m.get("name") or m.get("employee_id") or "") for m in selected
        )
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=self._format_routing_decision_message(selected_names, rationale),
            kind="routing_decision",
            status="completed" if selected else "blocked",
            payload={
                "task": task,
                "target_employee_ids": [str(m.get("employee_id") or "") for m in selected],
                "discussion_rounds": rounds,
                "rationale": rationale,
            },
        )
        discussion_rows.append(row)
        if persist:
            self._append_messages([row])
        return discussion_rows, selected

    def _xiaoc_dispatch_assessment(self, *, task: str, candidates: list[dict[str, Any]]) -> str:
        difficulty = self._dispatch_difficulty(task)
        difficulty_label = {
            "simple": "简单",
            "medium": "中等",
            "large": "较大",
        }.get(difficulty, "中等")
        candidate_names = "、".join(
            str(m.get("name") or m.get("employee_id") or "")
            for m in candidates
            if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        )
        if difficulty == "simple":
            strategy = "先讨论是否需要拆分；若无跨端风险，只选 1 个最合适负责人。"
        elif difficulty == "large":
            strategy = "先讨论模块边界和风险，再按职责拆给多人并行，避免多人做同一件事。"
        else:
            strategy = "先讨论工作量和风险，优先选 1 个负责人；只有跨端或需要复核时才加第 2 人。"
        return (
            "【任务讨论】小C先评估，再选负责人。\n"
            f"难度：{difficulty_label}\n"
            f"候选：{candidate_names or '暂无超级员工'}\n"
            f"策略：{strategy}"
        )

    def _discussion_round_count(self) -> int:
        return max(1, min(SUPER_DISCUSSION_DEFAULT_ROUNDS, SUPER_DISCUSSION_MAX_ROUNDS))

    async def _super_discussion_reply(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        history: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        round_index: int,
    ) -> str:
        me = str(member.get("name") or member.get("employee_id") or "超级员工")
        group_name = str(group.get("name") or "AI 群聊")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        prior = "\n".join(
            f"{turn.get('name')}：{turn.get('body')}" for turn in discussion_turns[-6:]
        )
        system = (
            f"你是群聊「{group_name}」里的超级员工「{me}」。群成员有：{roster}。\n"
            "这是执行前讨论阶段，只能做判断、拆解和建议，不要声称已经执行，不要调用 CLI，不要修改文件。\n"
            "讨论最多 1-2 轮，所以每次发言必须短、具体、可分工。\n"
            "先判断任务难度和工作量：简单任务建议只派一个最合适 CLI；只有跨领域或工作量大才多人并行，避免多人做同一件事。"
        )
        user_content = (
            f"【用户任务】\n{task}\n\n"
            f"【群最近对话】\n{transcript or '无'}\n\n"
            f"【前序讨论】\n{prior or '无'}\n\n"
            f"第 {round_index} 轮，请以「{me}」身份给出你的执行判断："
            "任务难不难、是否值得拆、你适合负责什么、需要谁配合、下一步如何派工。用 1-2 句话。"
        )
        try:
            res = await asyncio.wait_for(
                self._completion_fn(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=_discussion_completion_timeout_sec(),
            )
        except TimeoutError:
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型讨论超时",
            )
        except Exception:  # noqa: BLE001
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="我这边暂时不能参与讨论",
            )
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            content = str(res["content"]).strip()[:600]
            if not self._discussion_reply_is_placeholder(content):
                return content
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型回复过于空泛",
            )
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return self._fallback_super_discussion_reply(
            group=group,
            member=member,
            task=task,
            round_index=round_index,
            reason=err or "模型没有给出有效讨论",
        )

    def _fallback_super_discussion_reply(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        round_index: int,
        reason: str = "",
    ) -> str:
        employee_id = str(member.get("employee_id") or "").strip()
        me = str(member.get("name") or employee_id or "超级员工")
        difficulty = self._dispatch_difficulty(task)
        difficulty_label = {
            "simple": "简单",
            "medium": "中等",
            "large": "较大",
        }.get(difficulty, "中等")
        group_members = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ]
        preferred = self._preferred_single_dispatch_target(group_members or [member], task)
        preferred_name = str(
            (preferred or {}).get("name") or (preferred or {}).get("employee_id") or me
        )
        focus = self._super_employee_focus(employee_id, task)
        if difficulty == "simple":
            split_advice = f"不建议拆分，派 {preferred_name} 一个负责人就够，避免重复消耗。"
        elif difficulty == "large":
            split_advice = "建议按端侧、服务端、验收边界拆开并行，各自只做自己的部分。"
        else:
            split_advice = f"先派 {preferred_name} 主责推进；只有遇到跨端阻塞再加第二人。"
        collaboration = {
            "codex-super-employee": "我适合补服务端链路、接口状态和自动化测试证据。",
            "cursor-super-employee": "我适合看移动端页面、交互细节和可见 UI 结果。",
            "claude-super-employee": "我适合做验收口径、风险收口和是否需要拆分的判断。",
            "trae-super-employee": "我适合承接 Trae 执行端、IDE 自动化和备用额度执行。",
        }.get(employee_id, f"我适合负责{focus}。")
        reason_line = f"（{reason}，走确定性讨论兜底）" if reason else ""
        return (
            f"{me}：我判断这是{difficulty_label}任务，{split_advice}"
            f"{collaboration}如果派到我，我只处理这条边界，并在群里回报改动文件、命令和测试结果。{reason_line}"
        )[:600]

    @staticmethod
    def _discussion_reply_is_placeholder(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return True
        compact = text.replace(" ", "")
        if len(compact) <= 18 and any(k in compact for k in ("收到", "待命", "执行", "派工")):
            return True
        generic_markers = ("按职责待命", "等派工", "派到我", "收到", "先判断再派工")
        judgment_markers = (
            "判断",
            "简单",
            "中等",
            "较大",
            "难度",
            "工作量",
            "拆",
            "负责人",
            "适合",
            "风险",
            "建议",
        )
        has_judgment = any(k in text for k in judgment_markers)
        if len(compact) <= 34 and not has_judgment:
            return True
        return any(k in text for k in generic_markers) and not has_judgment

    async def _route_after_discussion(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        mentions: list[str] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        if self._is_broadcast_mention(task) or self._explicit_member_ids(
            candidates, task, mentions
        ):
            return candidates[:MAX_RESPONDERS], "用户已明确点名或广播，按指定成员执行。"
        candidate_lines = "\n".join(
            f"- {m.get('employee_id')}: {m.get('name')}，{m.get('summary')}" for m in candidates
        )
        discussion = "\n".join(
            f"{turn.get('name')}：{turn.get('body')}" for turn in discussion_turns
        )
        system = (
            "你是 XCAGI 群聊工作流调度器。请根据任务、候选员工和讨论，"
            "先判断工作量，再选择最少但足够的执行员工。简单任务只能选 1 人；"
            "中等任务优先 1 人、最多 2 人；大任务才多人并行，且不能让多人做同一件事。"
            "只输出 JSON，不要输出 Markdown。"
        )
        user_content = (
            f"【群】{group.get('name')}\n"
            f"【任务】{task}\n"
            f"【候选员工】\n{candidate_lines}\n"
            f"【讨论】\n{discussion or '无'}\n\n"
            '输出格式：{"difficulty":"simple|medium|large","target_employee_ids":["..."],"rationale":"一句话说明任务难度、为什么派这些人"}'
        )
        difficulty = self._dispatch_difficulty(task)
        try:
            res = await asyncio.wait_for(
                self._completion_fn(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=_discussion_completion_timeout_sec(),
            )
            content = str(res.get("content") or "") if isinstance(res, dict) else ""
            target_ids, rationale = self._parse_routing_json(content, candidates)
            if target_ids:
                by_id = {str(m.get("employee_id") or ""): m for m in candidates}
                selected = [by_id[eid] for eid in target_ids if eid in by_id]
                if difficulty == "simple":
                    selected = selected[:1]
                if selected:
                    return selected[:MAX_RESPONDERS], rationale or "按讨论结论分流执行。"
        except Exception:  # noqa: BLE001 - 调度 LLM 不可用时走确定性兜底
            pass
        selected = self._heuristic_dispatch_targets(candidates, task)
        names = "、".join(str(m.get("name") or m.get("employee_id") or "") for m in selected)
        difficulty_label = {"simple": "简单任务", "medium": "中等任务", "large": "大任务"}.get(
            difficulty, "任务"
        )
        return selected, f"{difficulty_label}，按工作量和成员职责分工给：{names or '无'}。"

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
        if AiGroupChatDispatchMixin._dispatch_difficulty(task) == "simple":
            preferred = AiGroupChatDispatchMixin._preferred_single_dispatch_target(candidates, task)
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
        preferred = AiGroupChatDispatchMixin._preferred_single_dispatch_target(candidates, task)
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

    async def _ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        employee_id = str(member.get("employee_id") or "")
        # 超级员工走专用 invoke 通道（CLI 直答 / Para 多设备派工）
        if employee_id in _SUPER_EMPLOYEE_IDS:
            return await self._super_employee_reply(group, member, history, user_id=user_id)
        group_name = str(group.get("name") or "AI 群聊")
        me = str(member.get("name") or member.get("employee_id"))
        summary = str(member.get("summary") or "")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        system = (
            f"你是群聊「{group_name}」里的 AI 成员「{me}」。{summary}\n"
            f"群成员有：{roster}。\n"
            "请只代表你自己、用一两句话简洁地回应群里用户的最新消息；"
            "不要替其他成员发言，不要复述别人说过的话，不要加“作为AI”之类的免责声明。"
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        user_content = f"【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息。"
        try:
            res = await self._completion_fn(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            return str(res["content"]).strip()
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return f"（{me} 暂时无法回应{f'：{err}' if err else ''}）"

    async def _dispatch_work(
        self,
        *,
        group: dict[str, Any],
        members: list[dict[str, Any]],
        task: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        work_order_id = uuid.uuid4().hex
        assignments = self._build_dispatch_assignments(task, members)
        target_names = [str(a.get("name") or a.get("employee_id") or "") for a in assignments]
        work_order_row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=self._format_work_order_message(
                task,
                target_names,
                assignments=assignments,
                branch_context=branch_context,
            ),
            kind="work_order",
            status="assigned" if assignments else "blocked",
            work_order_id=work_order_id,
            payload={
                "task": task,
                "branch_context": branch_context,
                "target_employee_ids": [str(a.get("employee_id") or "") for a in assignments],
                "assignments": [
                    {
                        "employee_id": str(a.get("employee_id") or ""),
                        "employee_name": str(a.get("name") or a.get("employee_id") or ""),
                        "focus": str(a.get("assignment_focus") or ""),
                        "task": str(a.get("assigned_task") or task),
                    }
                    for a in assignments
                ],
            },
        )
        messages: list[dict[str, Any]] = [work_order_row]
        if persist:
            self._append_messages([work_order_row])
        if not assignments:
            return messages, [
                {
                    "work_order_id": work_order_id,
                    "status": "blocked",
                    "task": task,
                    "branch_context": branch_context,
                    "target_employee_ids": [],
                }
            ]

        work_orders: list[dict[str, Any]] = []
        for member in assignments:
            report = await self._execute_employee_work(
                group=group,
                member=member,
                task=task,
                assigned_task=str(member.get("assigned_task") or task),
                assignment_focus=str(member.get("assignment_focus") or ""),
                work_order_id=work_order_id,
                user_id=user_id,
                sender_name=sender_name,
                branch_context=branch_context,
            )
            work_orders.append(report)
            row = self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(member.get("employee_id") or ""),
                sender_name=str(member.get("name") or member.get("employee_id") or ""),
                sender_avatar=str(member.get("avatar") or ""),
                body=self._format_work_report_message(member, report),
                kind="work_report",
                status=str(report.get("status") or ""),
                work_order_id=work_order_id,
                payload=report,
            )
            messages.append(row)
            if persist:
                self._append_messages([row])
            progress = self._initial_relay_progress_from_report(
                user_id=user_id,
                group_id=group_id,
                report_row=row,
            )
            if progress is not None:
                messages.append(progress)
                if persist:
                    self._append_messages([progress])
        return messages, work_orders

    def _initial_relay_progress_from_report(
        self,
        *,
        user_id: int,
        group_id: str,
        report_row: dict[str, Any],
    ) -> dict[str, Any] | None:
        task_id = self._report_relay_task_id(report_row)
        if not task_id:
            return None
        status = str(report_row.get("status") or "").strip().lower()
        if status not in {"queued", "accepted", "assigned", "running", "processing", "in_progress"}:
            return None
        payload = report_row.get("payload") if isinstance(report_row.get("payload"), dict) else {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task = {
            "task_id": task_id,
            "relay_id": str(raw.get("relay_id") or ""),
            "kind": str(raw.get("kind") or ""),
        }
        return self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=str(report_row.get("sender_id") or ""),
            sender_name=str(report_row.get("sender_name") or "负责人"),
            sender_avatar=str(report_row.get("sender_avatar") or ""),
            body=self._format_relay_progress_message(
                report=report_row,
                task=task,
                status=status,
            ),
            kind="work_progress",
            status=status,
            work_order_id=str(report_row.get("work_order_id") or ""),
            payload={
                "work_order_id": str(report_row.get("work_order_id") or ""),
                "employee_id": str(report_row.get("sender_id") or ""),
                "employee_name": str(report_row.get("sender_name") or ""),
                "status": status,
                "summary": self._relay_progress_summary(status, task_id),
                "raw": task,
            },
        )
