"""Bounded pre-dispatch discussion and target routing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from app.application.group_chat.constants import (
    _SUPER_EMPLOYEE_IDS,
    _XIAOC_ASSISTANT_ID,
    CONTEXT_TURNS,
    MAX_RESPONDERS,
    SUPER_DISCUSSION_DEFAULT_ROUNDS,
    SUPER_DISCUSSION_MAX_ROUNDS,
    CompletionFn,
)
from app.application.group_chat.dispatch_targeting import DispatchTargeting
from app.application.group_chat.ports import (
    MessageFactory,
    MessageStore,
    RouteDiscussion,
    SuperDiscussionReply,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class GroupDiscussion:
    def __init__(
        self,
        messages: MessageStore,
        make_row: MessageFactory,
        *,
        complete: CompletionFn,
        timeout: Callable[[], float],
        reply: SuperDiscussionReply,
        route: RouteDiscussion,
    ) -> None:
        self.messages = messages
        self.make_row = make_row
        self.complete = complete
        self.timeout = timeout
        self.reply = reply
        self.route = route

    async def run_super_discussion_then_route(
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
        rounds = GroupDiscussion.discussion_round_count()
        assessment = GroupDiscussion.xiaoc_dispatch_assessment(task=task, candidates=candidates)
        discussion_turns.append(
            {
                "employee_id": _XIAOC_ASSISTANT_ID,
                "name": "小C助理",
                "body": assessment,
                "round": "0",
            }
        )
        assessment_row = self.make_row(
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
                "difficulty": DispatchTargeting.dispatch_difficulty(task),
            },
        )
        discussion_rows.append(assessment_row)
        if persist:
            self.messages.append([assessment_row])
        for round_index in range(1, rounds + 1):
            for member in super_members:
                content = await self.reply(
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
                row = self.make_row(
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
                    self.messages.append([row])
        selected, rationale = await self.route(
            group=group,
            task=task,
            candidates=candidates,
            discussion_turns=discussion_turns,
            mentions=mentions,
        )
        selected_names = "、".join(
            str(m.get("name") or m.get("employee_id") or "") for m in selected
        )
        row = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=DispatchTargeting.format_routing_decision_message(selected_names, rationale),
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
            self.messages.append([row])
        return (discussion_rows, selected)

    @staticmethod
    def xiaoc_dispatch_assessment(*, task: str, candidates: list[dict[str, Any]]) -> str:
        difficulty = DispatchTargeting.dispatch_difficulty(task)
        difficulty_label = {"simple": "简单", "medium": "中等", "large": "较大"}.get(
            difficulty, "中等"
        )
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
        return f"【任务讨论】小C先评估，再选负责人。\n难度：{difficulty_label}\n候选：{candidate_names or '暂无超级员工'}\n策略：{strategy}"

    @staticmethod
    def discussion_round_count() -> int:
        return max(1, min(SUPER_DISCUSSION_DEFAULT_ROUNDS, SUPER_DISCUSSION_MAX_ROUNDS))

    async def super_discussion_reply(
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
        system = f"你是群聊「{group_name}」里的超级员工「{me}」。群成员有：{roster}。\n这是执行前讨论阶段，只能做判断、拆解和建议，不要声称已经执行，不要调用 CLI，不要修改文件。\n讨论最多 1-2 轮，所以每次发言必须短、具体、可分工。\n先判断任务难度和工作量：简单任务建议只派一个最合适 CLI；只有跨领域或工作量大才多人并行，避免多人做同一件事。"
        user_content = f"【用户任务】\n{task}\n\n【群最近对话】\n{transcript or '无'}\n\n【前序讨论】\n{prior or '无'}\n\n第 {round_index} 轮，请以「{me}」身份给出你的执行判断：任务难不难、是否值得拆、你适合负责什么、需要谁配合、下一步如何派工。用 1-2 句话。"
        try:
            res = await asyncio.wait_for(
                self.complete(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=self.timeout(),
            )
        except TimeoutError:
            return GroupDiscussion.fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型讨论超时",
            )
        except RECOVERABLE_ERRORS:
            return GroupDiscussion.fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="我这边暂时不能参与讨论",
            )
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            content = str(res["content"]).strip()[:600]
            if not GroupDiscussion.discussion_reply_is_placeholder(content):
                return content
            return GroupDiscussion.fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型回复过于空泛",
            )
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return GroupDiscussion.fallback_super_discussion_reply(
            group=group,
            member=member,
            task=task,
            round_index=round_index,
            reason=err or "模型没有给出有效讨论",
        )

    @staticmethod
    def fallback_super_discussion_reply(
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        round_index: int,
        reason: str = "",
    ) -> str:
        employee_id = str(member.get("employee_id") or "").strip()
        me = str(member.get("name") or employee_id or "超级员工")
        difficulty = DispatchTargeting.dispatch_difficulty(task)
        difficulty_label = {"simple": "简单", "medium": "中等", "large": "较大"}.get(
            difficulty, "中等"
        )
        group_members = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ]
        preferred = DispatchTargeting.preferred_single_dispatch_target(
            group_members or [member], task
        )
        preferred_name = str(
            (preferred or {}).get("name") or (preferred or {}).get("employee_id") or me
        )
        focus = DispatchTargeting.super_employee_focus(employee_id, task)
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
        return f"{me}：我判断这是{difficulty_label}任务，{split_advice}{collaboration}如果派到我，我只处理这条边界，并在群里回报改动文件、命令和测试结果。{reason_line}"[
            :600
        ]

    @staticmethod
    def discussion_reply_is_placeholder(content: str) -> bool:
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
        if len(compact) <= 34 and (not has_judgment):
            return True
        return any(k in text for k in generic_markers) and (not has_judgment)

    async def route_after_discussion(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        mentions: list[str] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        if DispatchTargeting.is_broadcast_mention(task) or DispatchTargeting.explicit_member_ids(
            candidates, task, mentions
        ):
            return (candidates[:MAX_RESPONDERS], "用户已明确点名或广播，按指定成员执行。")
        candidate_lines = "\n".join(
            f"- {m.get('employee_id')}: {m.get('name')}，{m.get('summary')}" for m in candidates
        )
        discussion = "\n".join(
            f"{turn.get('name')}：{turn.get('body')}" for turn in discussion_turns
        )
        system = "你是 XCAGI 群聊工作流调度器。请根据任务、候选员工和讨论，先判断工作量，再选择最少但足够的执行员工。简单任务只能选 1 人；中等任务优先 1 人、最多 2 人；大任务才多人并行，且不能让多人做同一件事。只输出 JSON，不要输出 Markdown。"
        user_content = f"""【群】{group.get("name")}\n【任务】{task}\n【候选员工】\n{candidate_lines}\n【讨论】\n{discussion or "无"}\n\n输出格式：{{"difficulty":"simple|medium|large","target_employee_ids":["..."],"rationale":"一句话说明任务难度、为什么派这些人"}}"""
        difficulty = DispatchTargeting.dispatch_difficulty(task)
        try:
            res = await asyncio.wait_for(
                self.complete(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=self.timeout(),
            )
            content = str(res.get("content") or "") if isinstance(res, dict) else ""
            target_ids, rationale = DispatchTargeting.parse_routing_json(content, candidates)
            if target_ids:
                by_id = {str(m.get("employee_id") or ""): m for m in candidates}
                selected = [by_id[eid] for eid in target_ids if eid in by_id]
                if difficulty == "simple":
                    selected = selected[:1]
                if selected:
                    return (selected[:MAX_RESPONDERS], rationale or "按讨论结论分流执行。")
        except RECOVERABLE_ERRORS:
            pass
        selected = DispatchTargeting.heuristic_dispatch_targets(candidates, task)
        names = "、".join(str(m.get("name") or m.get("employee_id") or "") for m in selected)
        difficulty_label = {"simple": "简单任务", "medium": "中等任务", "large": "大任务"}.get(
            difficulty, "任务"
        )
        return (selected, f"{difficulty_label}，按工作量和成员职责分工给：{names or '无'}。")
