"""平台制作 Token：管理端同源聚合的公开快照。

与「平台使用 Token」（线上对话 + AI 员工账本）区分：
- 制作 = FHD 本地账本 + Cursor + Codex + Trae + mimo（管理端 /admin/token-usage）
- 使用 = llm_call_logs + employee_execution_metrics（官网可视化实时账本）

公开快照只保留聚合数字，不含路径、会话明细或 by_model 明细。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

_SOURCE_LABELS = {
    "local": "FHD 本地账本",
    "cursor": "Cursor",
    "codex": "Codex",
    "trae": "Trae",
    "mimo": "mimo",
}


def _repo_root() -> Path:
    # FHD/app/infrastructure/billing → XCMAX/
    return Path(__file__).resolve().parents[4]


def public_snapshot_path() -> Path:
    configured = (os.environ.get("XIUCI_PLATFORM_MADE_TOKENS_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _repo_root() / "成都修茈科技有限公司" / "data" / "platform_made_tokens.json"


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_public_snapshot(summary: Mapping[str, Any]) -> dict[str, Any]:
    """把管理端 token-usage 摘要收敛为官网可公开字段。"""
    sources_in = summary.get("sources") if isinstance(summary.get("sources"), Mapping) else {}
    sources_out: list[dict[str, Any]] = []
    for key in ("local", "cursor", "codex", "trae", "mimo"):
        raw = sources_in.get(key) if isinstance(sources_in, Mapping) else None
        raw = raw if isinstance(raw, Mapping) else {}
        available = bool(raw.get("available"))
        sources_out.append(
            {
                "key": key,
                "label": _SOURCE_LABELS.get(key, key),
                "available": available,
                "total_tokens": _to_int(raw.get("total_tokens")) if available else 0,
                "estimated": bool(raw.get("estimated")),
            }
        )
    return {
        "schema": "xiu-ci.platform-made-tokens/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "collected_at": str(summary.get("collected_at") or ""),
        "platform_made_tokens": _to_int(summary.get("grand_total_tokens")),
        "platform_made_prompt_tokens": _to_int(summary.get("grand_prompt_tokens")),
        "platform_made_completion_tokens": _to_int(summary.get("grand_completion_tokens")),
        "sources": sources_out,
        "definition": (
            "管理端同源算法：FHD 本地账本 + Cursor + Codex + Trae + mimo 五源合计；"
            "与线上对话/AI 员工「平台使用 Token」分开统计"
        ),
    }


def write_public_snapshot(summary: Mapping[str, Any], *, path: Path | None = None) -> Path:
    target = path or public_snapshot_path()
    payload = build_public_snapshot(summary)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_public_snapshot(*, path: Path | None = None) -> dict[str, Any] | None:
    target = path or public_snapshot_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if _to_int(raw.get("platform_made_tokens")) < 0:
        return None
    return raw
