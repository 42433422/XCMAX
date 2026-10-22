"""Grounded report excerpts and craft-workshop standby descriptions."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _craft_pipeline_standby_context(pkg_id: str, signals: Dict[str, Any]) -> Dict[str, Any]:
    """给待机汇报补充流水线语境，避免 LLM 误判为缺上游故障。"""
    raw_deps = signals.get("depends_on")
    deps = raw_deps if isinstance(raw_deps, list) else []
    upstream = [str(d).strip() for d in deps if str(d).strip()]
    downstream_hint: Dict[str, List[str]] = {
        "intent-analyst": ["employee-planner", "artifact-generator"],
        "employee-planner": ["artifact-generator", "quality-validator"],
        "artifact-generator": ["quality-validator", "miniapp-builder"],
        "workflow-automator": ["pack-registrar"],
        "pack-registrar": ["sandbox-tester"],
        "sandbox-tester": ["code-validator", "self-checker"],
    }
    return {
        "mode": "all_hands_standby",
        "pipeline_area": "craft-workshop",
        "instruction": "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 告警。说明本岗在制作车间 13 步流水线中的位置、depends_on 与就绪条件即可。",
        "upstream_employees": upstream,
        "typical_downstream": downstream_hint.get(pkg_id, []),
        "synthetic_upstream_note": "当前无真实上游产物属预期；用 manifest 描述待机职责，勿写「输入不足」。",
    }


def _is_standby_pipeline_json_noise(text: str) -> bool:
    t = (text or "").strip()
    if not t.startswith("{"):
        return False
    if "输入不足" not in t and '"warnings"' not in t:
        return False
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return "输入不足" in t and "warnings" in t.lower()
    if not isinstance(obj, dict):
        return False
    warns = obj.get("warnings")
    return isinstance(warns, list) and any(("输入不足" in str(w) for w in warns))


def _coerce_standby_excerpt(text: str, row: Dict[str, Any]) -> str:
    """把待机误输出的流水线 JSON 告警压成可读一句，避免污染会议摘要。"""
    if not _is_standby_pipeline_json_noise(text):
        return text
    eid = str(row.get("employee_id") or "").strip()
    name = str(row.get("name") or eid).strip()
    area = str(row.get("area") or "制作车间").strip() or "制作车间"
    summ = ""
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            summ = str(obj.get("summary") or "").strip()
    except json.JSONDecodeError:
        pass
    if summ and (not summ.startswith("{")) and ("输入不足" not in summ[:80]):
        return summ
    return f"【{name}】（{eid}）在 {area} 流水线中处于**待机**：职责与 manifest 已就绪，等待上游工单/产物输入；本次大会未执行流水线步骤，无异常。"


def _employee_answer_excerpt(row: Dict[str, Any], *, max_chars: int = 800) -> str:
    md = str(row.get("report_markdown") or "").strip()
    if md:
        if row.get("report_mode") == "standby_manifest_bench" or _is_standby_pipeline_json_noise(
            md
        ):
            md = _coerce_standby_excerpt(md, row)
        return md[:max_chars]
    err = str(row.get("cognition_error") or "").strip()
    if err:
        return f"（员工执行失败：{err}）"
    warns = row.get("warnings") or []
    if isinstance(warns, list) and warns:
        filtered = [
            str(w)
            for w in warns
            if str(w).strip()
            and "输入不足" not in str(w)
            and ("research failed" not in str(w).lower())
        ]
        if filtered:
            return f"（员工无报告，警告：{'; '.join(filtered)[:max_chars]}）"
    return "（员工无报告）"
