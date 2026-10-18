"""Codex 模型网关在 MODstore 侧的两端约定（与 Mac 端 codex_model_gateway.mjs 对齐）。

- 派发侧：``MODSTORE_PARA_CODEX_MODEL_CANDIDATES`` 或请求里的 ``codex_model_candidates``
  以 ``- codex_model_candidates: a,b,c`` 写进 Para 提示，Mac 端按此顺序探活 + 降级。
  未配置时不写，Mac 端用自身默认（gpt-5.6-sol > gpt-5.6-terra > gpt-5.6-luna）。
- 回写侧：从 Para 任务失败文本里解析 ``codex_models_tried=model:status,...``，
  作为结构化字段写入岗位摘要与工单内部动作（客户视图不展示）。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

_MODEL_RE = re.compile(r"^[A-Za-z0-9._:\-/]{1,64}$")
_TRIED_RE = re.compile(r"codex_models_tried=([A-Za-z0-9._:\-/,]+)")
_STATUSES = {"ok", "unsupported", "quota", "failed", "skipped"}
_MAX_MODELS = 8


def _split_models(raw: Any) -> List[str]:
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = re.split(r"[,\s>]+", str(raw or ""))
    out: List[str] = []
    for item in items:
        item = item.strip()
        if item and _MODEL_RE.match(item) and item not in out:
            out.append(item)
    return out[:_MAX_MODELS]


def codex_model_candidates_line(req: Dict[str, Any]) -> str:
    raw = req.get("codex_model_candidates") or os.environ.get(
        "MODSTORE_PARA_CODEX_MODEL_CANDIDATES", ""
    )
    models = _split_models(raw)
    return f"- codex_model_candidates: {','.join(models)}" if models else ""


def parse_codex_models_tried(*texts: Any) -> List[Dict[str, str]]:
    """返回最后一次出现的尝试列表 [{model, status}]；无标记返回 []。"""
    found: List[Dict[str, str]] = []
    for text in texts:
        for match in _TRIED_RE.finditer(str(text or "")):
            rows: List[Dict[str, str]] = []
            for part in match.group(1).split(","):
                model, _, status = part.rpartition(":")
                if model and _MODEL_RE.match(model) and status in _STATUSES:
                    rows.append({"model": model, "status": status})
            if rows:
                found = rows[:_MAX_MODELS]
    return found
