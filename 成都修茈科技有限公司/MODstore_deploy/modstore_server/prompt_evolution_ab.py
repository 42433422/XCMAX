"""Prompt 进化影子 A/B：历史失败任务回放，胜出则自动应用，失败则还原。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _ab_enabled() -> bool:
    return os.environ.get("MODSTORE_PROMPT_EVOLUTION_AB_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _auto_apply_enabled() -> bool:
    return os.environ.get("MODSTORE_PROMPT_EVOLUTION_AUTO_APPLY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _override_dir() -> Path:
    raw = os.environ.get(
        "MODSTORE_PROMPT_OVERRIDE_DIR",
        "playwright-report/prompt-overrides",
    ).strip()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = Path(repo_root())
    except Exception:
        root = Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()
    return root / raw


def _load_prompt_override(employee_id: str) -> Optional[str]:
    path = _override_dir() / f"{employee_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("system_prompt") or "").strip() or None
    except Exception:
        return None


def apply_prompt_override(
    employee_id: str, system_prompt: str, *, meta: Dict[str, Any]
) -> Dict[str, Any]:
    """写入 prompt override 文件（可还原）。"""
    d = _override_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{employee_id}.json"
    backup_path = d / f"{employee_id}.backup.json"
    if path.is_file():
        try:
            backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    payload = {
        "employee_id": employee_id,
        "system_prompt": system_prompt,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path)}


def revert_prompt_override(employee_id: str) -> Dict[str, Any]:
    d = _override_dir()
    path = d / f"{employee_id}.json"
    backup = d / f"{employee_id}.backup.json"
    if backup.is_file():
        path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        return {"ok": True, "reverted_from": str(backup)}
    if path.is_file():
        path.unlink()
        return {"ok": True, "removed": True}
    return {"ok": True, "skipped": True, "reason": "no override"}


def get_effective_system_prompt(employee_id: str, manifest_prompt: str) -> str:
    """employee_runtime 可读：override 优先于 manifest。"""
    ov = _load_prompt_override(employee_id)
    return ov if ov else manifest_prompt


def _fetch_failed_tasks(employee_id: str, *, lookback_hours: int, limit: int = 3) -> List[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        from sqlalchemy import or_

        from modstore_server.llm_failure_classifier import FAILURE_KIND_QUOTA
        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(EmployeeExecutionMetric)
                .filter(
                    EmployeeExecutionMetric.employee_id == employee_id,
                    EmployeeExecutionMetric.created_at >= cutoff,
                    EmployeeExecutionMetric.status != "success",
                    # 排除配额/计费失败：拿额度耗尽的任务回放评审 prompt 既是无谓 LLM 调用，
                    # 又会让 A/B 误判而还原本来更好的新 prompt。
                    or_(
                        EmployeeExecutionMetric.failure_kind.is_(None),
                        EmployeeExecutionMetric.failure_kind != FAILURE_KIND_QUOTA,
                    ),
                )
                .order_by(EmployeeExecutionMetric.id.desc())
                .limit(limit)
                .all()
            )
        return [str(r.task or "").strip() for r in rows if str(r.task or "").strip()]
    except Exception:
        return []


async def _judge_prompt_pair(
    *,
    task_brief: str,
    prompt_before: str,
    prompt_after: str,
) -> str:
    """LLM 判断哪条 prompt 更可能成功完成该失败任务。返回 before|after|tie。"""
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        resolve_platform_bench_llm,
    )

    prov, mdl = resolve_platform_bench_llm()
    if not prov or not mdl:
        return "tie"

    messages = [
        {
            "role": "system",
            "content": (
                "你是员工 prompt 评审员。给定一条失败任务与两条 system_prompt，"
                "判断哪条更可能让 AI 员工正确完成该任务。"
                "只输出一个词：before、after 或 tie。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"失败任务：\n{task_brief[:2000]}\n\n"
                f"--- prompt_before ---\n{prompt_before[:4000]}\n\n"
                f"--- prompt_after ---\n{prompt_after[:4000]}"
            ),
        },
    ]
    try:
        out = await chat_dispatch_via_platform_only(prov, mdl, messages, max_tokens=16)
        verdict = str(out or "").strip().lower()
        if "after" in verdict:
            return "after"
        if "before" in verdict:
            return "before"
        return "tie"
    except Exception:
        return "tie"


def run_prompt_shadow_ab(
    *,
    employee_id: str,
    prompt_before: str,
    prompt_after: str,
    lookback_hours: int = 24,
    min_wins: int = 2,
) -> Dict[str, Any]:
    """同步入口：影子 A/B 回放。"""
    if not _ab_enabled():
        return {"ok": True, "skipped": True, "reason": "ab disabled"}

    from modstore_server.runtime_async import run_coro_sync

    tasks = _fetch_failed_tasks(employee_id, lookback_hours=lookback_hours, limit=3)
    if not tasks:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no failed tasks for replay",
            "verdict": "tie",
        }

    wins_after = 0
    wins_before = 0
    details: List[Dict[str, str]] = []
    for task in tasks:
        verdict = run_coro_sync(
            _judge_prompt_pair(
                task_brief=task,
                prompt_before=prompt_before,
                prompt_after=prompt_after,
            )
        )
        details.append({"task_preview": task[:120], "verdict": verdict})
        if verdict == "after":
            wins_after += 1
        elif verdict == "before":
            wins_before += 1

    improved_wins = wins_after >= min_wins and wins_after > wins_before
    return {
        "ok": True,
        "verdict": "after" if improved_wins else ("before" if wins_before > wins_after else "tie"),
        "wins_after": wins_after,
        "wins_before": wins_before,
        "replay_count": len(tasks),
        "details": details,
        "improved_wins": improved_wins,
    }


def maybe_auto_apply_prompt_evolution(
    *,
    employee_id: str,
    prompt_before: str,
    prompt_after: str,
    evolution_record_id: int = 0,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """A/B 通过后自动应用 prompt override；失败则保持 suggested 状态。"""
    ab = run_prompt_shadow_ab(
        employee_id=employee_id,
        prompt_before=prompt_before,
        prompt_after=prompt_after,
        lookback_hours=lookback_hours,
    )
    if not ab.get("improved_wins"):
        return {"ok": True, "applied": False, "ab": ab}

    if not _auto_apply_enabled():
        return {"ok": True, "applied": False, "ab": ab, "reason": "auto_apply disabled"}

    apply_out = apply_prompt_override(
        employee_id,
        prompt_after,
        meta={"evolution_record_id": evolution_record_id, "ab": ab},
    )
    return {"ok": True, "applied": True, "ab": ab, "apply": apply_out}


__all__ = [
    "apply_prompt_override",
    "get_effective_system_prompt",
    "maybe_auto_apply_prompt_evolution",
    "revert_prompt_override",
    "run_prompt_shadow_ab",
]
