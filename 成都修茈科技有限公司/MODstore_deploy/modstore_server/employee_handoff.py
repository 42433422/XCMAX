"""员工任务转交（10 项成熟度第 6 项「会协作」）。

一个员工发现任务不是自己范围，要能 @ 对的人、生成协作线程、交接上下文，
而不是所有事都让每日编排员自己说。

触发点：employee_executor 在 cognition 解析后，
若 LLM 输出 ``handoff_to`` 字段，调用本模块把上下文交给目标员工。

流程：
  1. 校验 handoff_to 是真实存在的 employee_id（在 catalog_items 注册过）
  2. 创建协作线程（参与者 = 转交人 + 接收人）
  3. 投递交接消息（含 reason + context + 原 task）
  4. mentions 自动触发 EmployeeSuggestion → 可被 dispatcher 派单给目标员工

返回结构写到 result["handoff"]，由 human_report 反映。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

MAX_HANDOFF_DEPTH = max(1, int(os.environ.get("MODSTORE_HANDOFF_MAX_DEPTH", "4") or "4"))
"""每条原始任务最多链式 handoff N 次（默认 4）。"""


@dataclass
class HandoffDirective:
    to_employee_id: str
    task_brief: str
    input_data: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    priority: int = 5


def _coerce_directive(raw: Any, *, fallback_brief: str = "") -> Optional[HandoffDirective]:
    if not raw:
        return None
    if isinstance(raw, str):
        eid = raw.strip()
        return HandoffDirective(eid, fallback_brief or eid) if eid else None
    if not isinstance(raw, dict):
        return None
    eid = str(
        raw.get("to_employee_id") or raw.get("handoff_to") or raw.get("employee_id") or ""
    ).strip()
    if not eid:
        return None
    brief = str(raw.get("task_brief") or raw.get("task") or fallback_brief or "")[:500]
    input_data = raw.get("input_data") or raw.get("input") or {}
    if not isinstance(input_data, dict):
        input_data = {"_raw": str(input_data)[:1000]}
    reason = str(raw.get("reason") or raw.get("why") or "")[:500]
    try:
        priority = int(raw.get("priority") or 5)
    except Exception:
        priority = 5
    return HandoffDirective(
        to_employee_id=eid,
        task_brief=brief,
        input_data=input_data,
        reason=reason,
        priority=priority,
    )


def extract_handoff_directives(
    execution_outcome: Dict[str, Any],
    *,
    fallback_brief: str = "",
) -> List[HandoffDirective]:
    """从员工执行结果里把 handoff 指令拍平成有效列表。

    这是 ``employee_orchestrator`` 依赖的旧 API，保留它避免编排链路回归。
    新的 ``perform_handoff`` 只负责协作线程/建议单，不替代拓扑调度 handoff。
    """
    if not isinstance(execution_outcome, dict):
        return []
    candidates: List[Any] = []

    def _scan(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key in ("handoff", "handoffs", "handoff_to"):
            v = node.get(key)
            if v is not None:
                candidates.append(v)

    _scan(execution_outcome)
    inner = execution_outcome.get("result")
    _scan(inner)
    cog = (
        (inner or {}).get("cognition")
        if isinstance(inner, dict)
        else execution_outcome.get("cognition")
    )
    if isinstance(cog, dict):
        _scan(cog)
        action = cog.get("action")
        if isinstance(action, dict):
            _scan(action)

    flat: List[HandoffDirective] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for item in candidate:
                directive = _coerce_directive(item, fallback_brief=fallback_brief)
                if directive:
                    flat.append(directive)
        else:
            directive = _coerce_directive(candidate, fallback_brief=fallback_brief)
            if directive:
                flat.append(directive)
    return flat


def build_followup_subtasks(
    layer_results: List[Dict[str, Any]],
    *,
    visited: Set[str],
    depth: int,
    fallback_brief: str,
) -> List["Any"]:
    """根据上一层 results 构造下一层 SubTask。

    返回空列表表示没有 handoff 需要继续。
    """
    from modstore_server.task_router import SubTask

    if depth >= MAX_HANDOFF_DEPTH:
        logger.info("handoff: depth limit reached (%s), skipping further handoffs", depth)
        return []

    new_subtasks: List[SubTask] = []
    for result in layer_results:
        if not result or not result.get("ok", False):
            continue
        outcome = result.get("result") if isinstance(result.get("result"), dict) else result
        directives = extract_handoff_directives(outcome, fallback_brief=fallback_brief)
        if not directives:
            continue
        from_employee_id = str(result.get("employee_id") or "")
        for directive in directives:
            if not directive.to_employee_id or directive.to_employee_id in visited:
                logger.info("handoff: skip target=%s (visited or empty)", directive.to_employee_id)
                continue
            input_data = dict(directive.input_data or {})
            input_data.setdefault("_handoff_chain", []).append(
                {"from": from_employee_id, "reason": directive.reason, "depth": depth}
            )
            input_data.setdefault("upstream_results", {})[from_employee_id] = result
            new_subtasks.append(
                SubTask(
                    employee_id=directive.to_employee_id,
                    task_brief=directive.task_brief or fallback_brief,
                    input_data=input_data,
                    depends_on=[],
                    priority=directive.priority,
                )
            )
            visited.add(directive.to_employee_id)
    return new_subtasks


def _resolve_target_employee_id(raw: Any) -> str:
    """把 LLM 输出的 handoff_to 规整为合法 employee_id 字符串。
    支持字符串、列表（取第一个非空）、dict（取 .employee_id）。
    """
    if isinstance(raw, str):
        s = raw.strip()
        return s
    if isinstance(raw, list):
        for it in raw:
            s = str(it or "").strip()
            if s:
                return s
        return ""
    if isinstance(raw, dict):
        for k in ("employee_id", "id", "to", "target"):
            v = raw.get(k)
            s = str(v or "").strip()
            if s:
                return s
    return str(raw or "").strip()


def _target_exists(employee_id: str) -> bool:
    """检查目标员工是否在 catalog_items 注册过（避免 LLM 编造不存在的 ID）。"""
    if not employee_id:
        return False
    try:
        from modstore_server.models import CatalogItem, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = (
                session.query(CatalogItem)
                .filter(CatalogItem.artifact == "employee_pack")
                .filter(CatalogItem.pkg_id == employee_id)
                .first()
            )
            if row:
                return True
            # 兜底：like 模糊匹配（catalog 可能存了不同形式）
            row2 = (
                session.query(CatalogItem)
                .filter(CatalogItem.artifact == "employee_pack")
                .filter(CatalogItem.pkg_id.like(f"%{employee_id}%"))
                .first()
            )
            return row2 is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("handoff target_exists check failed employee_id=%s err=%s", employee_id, exc)
        return False


def perform_handoff(
    *,
    source_employee_id: str,
    target_employee_id: str,
    reason: str,
    context: str,
    original_task: str,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行任务转交：创建协作线程 + 投递交接消息。

    返回：
      {
        "ok": bool,
        "thread_id": int,
        "message_id": int,
        "from": str,
        "to": str,
        "reason": str,
        "skipped": bool,        # True 表示没真正转交（如目标不存在 / 转给自己）
        "skip_reason": str,
      }
    """
    src = str(source_employee_id or "").strip()
    tgt = str(target_employee_id or "").strip()
    reason_s = str(reason or "").strip()[:500]
    ctx_s = str(context or "").strip()[:2000]
    task_s = str(original_task or "").strip()[:1000]

    if not tgt:
        return {
            "ok": False,
            "skipped": True,
            "skip_reason": "handoff_to 为空",
            "from": src,
            "to": "",
        }
    if tgt == src:
        return {
            "ok": False,
            "skipped": True,
            "skip_reason": "不能转交给自己",
            "from": src,
            "to": tgt,
        }
    if not _target_exists(tgt):
        return {
            "ok": False,
            "skipped": True,
            "skip_reason": f"目标员工 {tgt} 不存在于 catalog_items（可能 LLM 编造）",
            "from": src,
            "to": tgt,
        }

    # 构造交接消息正文（人话，不是 JSON）
    msg_lines = [
        f"@{tgt} 我把一个任务转交给你：",
        "",
        f"**原任务**：{task_s}" if task_s else "**原任务**：（空）",
    ]
    if reason_s:
        msg_lines.append(f"**转交原因**：{reason_s}")
    if ctx_s:
        msg_lines.append(f"**上下文**：{ctx_s}")
    msg_lines.append("")
    msg_lines.append("请判断是否在你的职责范围；如果接手，请直接处理并回报。")
    content = "\n".join(msg_lines)

    try:
        from modstore_server.employee_autonomy_service import (
            create_collab_thread,
            create_employee_suggestion,
            post_collab_message,
        )
    except ImportError as exc:
        return {
            "ok": False,
            "skipped": True,
            "skip_reason": f"employee_autonomy_service 不可用: {exc}",
            "from": src,
            "to": tgt,
        }

    title = f"任务转交：{src} → {tgt}"
    if reason_s:
        title += f"（{reason_s[:60]}）"

    try:
        thread_out = create_collab_thread(
            title=title[:256],
            participants=[src, tgt],
            created_by_employee_id=src,
            context={
                "kind": "task_handoff",
                "from": src,
                "to": tgt,
                "reason": reason_s,
                "original_task": task_s,
                "extra": extra_payload or {},
            },
            emit_event=True,
        )
        thread_id = int(thread_out.get("thread_id") or 0)
        if thread_id <= 0:
            return {
                "ok": False,
                "skipped": True,
                "skip_reason": "create_collab_thread 未返回 thread_id",
                "from": src,
                "to": tgt,
            }

        # 投递交接消息：用 mentions=[] 避免触发 post_collab_message 内置的 auto_dispatch
        # （那条路径会同步 dispatch_subtasks 把目标员工真跑一遍，本员工会阻塞等待）。
        # 我们改为手动创建 suggestion + auto_dispatch=False，让 autonomy service 异步处理。
        msg_out = post_collab_message(
            thread_id=thread_id,
            sender_employee_id=src,
            content=content,
            mentions=[],
            payload={
                "kind": "task_handoff",
                "from": src,
                "to": tgt,
                "reason": reason_s,
                "original_task": task_s,
            },
            emit_event=True,
        )
        message_id = int(msg_out.get("message_id") or 0)

        # 手动创建转交建议单（不自动 dispatch），由 autonomy service / 编排员后续 pickup
        # 关键：emit_event=False 避免触发 incident_bus 的 employee.suggestion.created 监听器
        # （那条路径会 ingest_suggestion_event_payload + auto_dispatch=True，同步执行目标员工）
        suggestion_id = 0
        try:
            sg_out = create_employee_suggestion(
                source_employee_id=src,
                summary=f"任务转交：{src} → {tgt}（{reason_s[:80]}）",
                detail=content[:4000],
                payload={
                    "kind": "task_handoff",
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "from": src,
                    "to": tgt,
                    "reason": reason_s,
                    "original_task": task_s,
                    "context": ctx_s,
                },
                target_employee_ids=[tgt],
                kind="task_handoff",
                risk_level="low",
                thread_id=thread_id,
                emit_event=False,
                auto_dispatch=False,
            )
            suggestion_id = int(sg_out.get("suggestion_id") or 0)
        except Exception as _sg_exc:  # noqa: BLE001
            logger.debug("create suggestion for handoff failed: %s", _sg_exc)

        return {
            "ok": True,
            "skipped": False,
            "thread_id": thread_id,
            "message_id": message_id,
            "from": src,
            "to": tgt,
            "reason": reason_s,
            "suggestion_id": suggestion_id or None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("perform_handoff failed src=%s tgt=%s", src, tgt)
        return {
            "ok": False,
            "skipped": True,
            "skip_reason": f"执行异常: {exc}"[:300],
            "from": src,
            "to": tgt,
        }


__all__ = [
    "HandoffDirective",
    "MAX_HANDOFF_DEPTH",
    "build_followup_subtasks",
    "extract_handoff_directives",
    "perform_handoff",
    "_resolve_target_employee_id",
]
