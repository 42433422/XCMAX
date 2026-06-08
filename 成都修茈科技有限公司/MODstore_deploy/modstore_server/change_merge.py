"""变更冲突检测与 LLM 合并策略。

在 apply_employee_change_request 之前调用，检测目标文件是否已被其他 CR 修改。
支持 merge_strategy: "overwrite" | "fail_on_conflict" | "llm_merge"
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def detect_conflict(
    change_request_id: int,
    target_path: str,
) -> Tuple[bool, List[int]]:
    """检测 target_path 是否在本 CR 创建之后被其它已 applied CR 落盘修改过。

    优先用真实 git diff（``base_commit_sha`` → 当前 HEAD）判断；若 git 不可用，
    退回到旧逻辑（同路径的其它 CR 即视为冲突候选）。
    返回 ``(has_conflict, conflicting_cr_ids)``。
    """
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            current = session.get(EmployeeChangeRequest, int(change_request_id))
            if not current:
                return False, []

            created_at = current.created_at
            base_sha = str(current.base_commit_sha or "").strip()

            other_crs = (
                session.query(EmployeeChangeRequest)
                .filter(
                    EmployeeChangeRequest.id != int(change_request_id),
                    EmployeeChangeRequest.status.in_(["pending", "applied"]),
                )
                .all()
            )

            same_path: List[EmployeeChangeRequest] = []
            for cr in other_crs:
                try:
                    data = json.loads(cr.diff_blob or "{}")
                    if str(data.get("path") or "").strip() == target_path.strip():
                        same_path.append(cr)
                except Exception:
                    pass

            git_changed = _git_path_changed_since(base_sha, target_path) if base_sha else None

            if git_changed is True:
                applied_after_base = [
                    int(cr.id)
                    for cr in same_path
                    if (cr.status or "") == "applied"
                    and cr.applied_at is not None
                    and (created_at is None or cr.applied_at > created_at)
                ]
                if applied_after_base:
                    return True, applied_after_base
                return True, [int(cr.id) for cr in same_path if (cr.status or "") == "applied"]

            if git_changed is False:
                return False, []

            # git 信息缺失时的兜底：同 path 且在本 CR 之后创建/落地的视为冲突
            conflicting: List[int] = []
            for cr in same_path:
                ts = cr.applied_at or cr.created_at
                if created_at is None or ts is None or ts > created_at:
                    conflicting.append(int(cr.id))
            return len(conflicting) > 0, conflicting
    except Exception:
        logger.exception("detect_conflict failed for CR %d", change_request_id)
        return False, []


def _git_path_changed_since(base_sha: str, target_path: str) -> Optional[bool]:
    """``base_sha`` 之后 ``target_path`` 是否在 git 中发生过改动。

    返回 ``True`` / ``False`` / ``None``（git 不可用时）。
    """
    if not base_sha:
        return None
    try:
        import subprocess

        from modstore_server.cr_git_pipeline import is_git_repo
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
        if not is_git_repo(root):
            return None
        rel = (target_path or "").replace("\\", "/").lstrip("/").strip()
        if not rel:
            return None
        proc = subprocess.run(
            ["git", "diff", "--name-only", base_sha, "HEAD", "--", rel],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
        if proc.returncode != 0:
            return None
        return bool((proc.stdout or "").strip())
    except Exception:
        return None


def llm_merge_contents(original: str, content_a: str, content_b: str, path: str) -> str:
    """使用 LLM 合并两个版本的文件内容。

    失败时返回 content_b（后提交覆盖）。
    """
    try:
        from modstore_server.runtime_async import run_coro_sync
        from modstore_server.services.llm import chat_dispatch_via_session

        prompt = f"""你是一个代码合并专家。请将以下两个版本的文件合并为一个没有冲突标记的最终版本。

文件路径: {path}

=== 原始版本 ===
{original[:4000]}

=== 版本 A ===
{content_a[:4000]}

=== 版本 B ===
{content_b[:4000]}

请输出合并后的完整文件内容，不要加任何解释，不要加 markdown 代码块标记，直接输出文件内容："""

        messages = [{"role": "user", "content": prompt}]

        async def _inner() -> str:
            chunks = []
            async for chunk in chat_dispatch_via_session(
                messages=messages,
                provider="auto",
                model="auto",
                stream=False,
            ):
                if isinstance(chunk, str):
                    chunks.append(chunk)
                elif isinstance(chunk, dict):
                    chunks.append(chunk.get("content") or "")
            return "".join(chunks)

        merged = run_coro_sync(_inner())
        return merged.strip() if merged.strip() else content_b
    except Exception:
        logger.exception("llm_merge_contents failed for %s", path)
        return content_b


def resolve_conflict(
    change_request_id: int,
    merge_strategy: str,
) -> Dict[str, Any]:
    """按 merge_strategy 解决冲突。

    merge_strategy:
      "overwrite"       — 直接覆盖（忽略冲突）
      "fail_on_conflict"— 标记 conflicted 并返回 error
      "llm_merge"       — LLM 合并两个版本

    返回 {"ok": bool, "strategy": str, "merged_content": optional[str], ...}
    """
    try:
        from pathlib import Path

        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(EmployeeChangeRequest, int(change_request_id))
            if not row:
                return {"ok": False, "error": "CR not found"}

            data = json.loads(row.diff_blob or "{}")
            path = str(data.get("path") or "").strip()
            content_b = str(data.get("content") or "")
            ws = str(data.get("workspace_root") or row.workspace_root_hint or "").strip()

        if merge_strategy == "fail_on_conflict":
            sf2 = get_session_factory()
            with sf2() as session:
                row2 = session.get(EmployeeChangeRequest, int(change_request_id))
                if row2:
                    row2.status = "conflicted"
                    session.commit()
            return {
                "ok": False,
                "strategy": merge_strategy,
                "error": "conflict detected, manual resolution required",
            }

        if merge_strategy == "overwrite":
            return {"ok": True, "strategy": merge_strategy, "merged_content": content_b}

        if merge_strategy == "llm_merge":
            # 读取磁盘当前版本作为原始版本
            try:
                import os

                resolved = os.path.normpath(os.path.join(ws, path)) if ws else path
                original = (
                    Path(resolved).read_text(encoding="utf-8") if Path(resolved).exists() else ""
                )
            except Exception:
                original = ""

            merged = llm_merge_contents(original, original, content_b, path)
            return {"ok": True, "strategy": merge_strategy, "merged_content": merged}

        return {"ok": True, "strategy": "overwrite", "merged_content": content_b}

    except Exception as exc:
        logger.exception("resolve_conflict failed for CR %d", change_request_id)
        return {"ok": False, "error": str(exc)}


__all__ = ["detect_conflict", "resolve_conflict", "llm_merge_contents"]
