"""LLM 语义审查：在确定性六节之上，用 LLM 做业务合理性判断与人话摘要。

分工铁律：确定性六节是**地基**（逐格对账、哈希、重算，LLM 不可推翻）；LLM 负责
确定性代码天然看不见的东西——数值是否符合业务常理（如单日工时 >24h）、丢弃记录
是否可疑、警告的轻重缓急，并产出给业务人员看的中文摘要。

LLM finding 计入 verdict（severity=fail → FAIL，blame=semantic_llm），但报告
永远标注 source=llm 与原始依据；``payload.llm_strict=false`` 可把 LLM 的 fail
降级为 warn（防幻觉阻塞流水线）。LLM 不可用时本节 skipped，如实标注。
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.mod_sdk.errors import BOUNDARY_ERRORS

CallLLM = Callable[..., Awaitable[Dict[str, Any]]]

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_MAX_FINDINGS = 12
_MAX_WRITE_SAMPLES = 40


def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _sample_writes(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ph in plan.get("phases") or []:
        if not isinstance(ph, dict) or str(ph.get("phase")) != "cell_writes":
            continue
        for w in ph.get("writes") or []:
            if not isinstance(w, dict):
                continue
            out.append(
                {
                    "sheet": w.get("sheet"),
                    "row": w.get("row") or w.get("ref"),
                    "col": w.get("col"),
                    "value": w.get("value"),
                }
            )
            if len(out) >= _MAX_WRITE_SAMPLES:
                return out
    return out


def build_review_prompt(
    plan: Dict[str, Any],
    deterministic_sections: Dict[str, Any],
    rules: Optional[Dict[str, Any]],
    business_context: str,
) -> List[Dict[str, str]]:
    expected = plan.get("expected") if isinstance(plan.get("expected"), dict) else {}
    policy = (rules or {}).get("policy") if isinstance(rules, dict) else None
    det_summary = {
        name: {
            "status": sec.get("status"),
            "stats": sec.get("stats"),
            "issues": sec.get("issues", [])[:4],
        }
        for name, sec in deterministic_sections.items()
    }
    payload = {
        "确定性检查结论": det_summary,
        "映射员对账基准expected": {
            "records_in": expected.get("records_in"),
            "records_dropped": (expected.get("records_dropped") or [])[:_MAX_FINDINGS],
            "keys_matched": expected.get("keys_matched"),
            "keys_unmatched_source": expected.get("keys_unmatched_source"),
            "blocks_without_records": (expected.get("blocks_without_records") or [])[:20],
            "per_key_numeric_sum": expected.get("per_key_numeric_sum"),
        },
        "写入抽样": _sample_writes(plan),
        "业务参数policy": policy,
        "业务上下文": business_context or "（未提供）",
    }
    system = (
        "你是表格交付的业务质检员。确定性检查（逐格对账/哈希/重算）已完成且不容你推翻；"
        "你只负责业务合理性审查：数值是否符合常理（如单键数值合计异常大/小、负数、单日超 24 的工时类数值）、"
        "被丢弃的记录是否可疑（键名错字/漏人）、无记录的块是否需要提醒、警告的轻重。"
        '仅输出 JSON：{"findings": [{"severity": "fail"|"warn"|"info", "detail": str, "evidence": str}],'
        ' "summary_zh": str}。'
        "证据不足就用 info/warn，禁止编造数据；summary_zh 用两三句给业务人员讲清结论。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


async def llm_semantic_review(
    plan: Dict[str, Any],
    deterministic_sections: Dict[str, Any],
    call_llm: CallLLM,
    *,
    rules: Optional[Dict[str, Any]] = None,
    business_context: str = "",
    strict: bool = True,
) -> Dict[str, Any]:
    """返回 semantic 节 dict：{status, issues, stats, human_summary}。"""
    section: Dict[str, Any] = {"status": "pass", "issues": [], "stats": {}, "human_summary": ""}
    try:
        resp = await call_llm(
            build_review_prompt(plan, deterministic_sections, rules, business_context),
            max_tokens=1500,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        section["status"] = "warn"
        section["issues"].append(
            {"severity": "warn", "detail": f"LLM 调用异常，语义审查未完成：{exc}", "source": "llm"}
        )
        return section
    if not resp or not resp.get("ok"):
        section["status"] = "warn"
        section["issues"].append(
            {
                "severity": "warn",
                "detail": f"LLM 不可用，语义审查未完成：{(resp or {}).get('error') or 'no response'}",
                "source": "llm",
            }
        )
        return section

    data = _parse_llm_json(str(resp.get("content") or ""))
    if data is None:
        section["status"] = "warn"
        section["issues"].append(
            {
                "severity": "warn",
                "detail": "LLM 输出无法解析为 JSON，语义审查未完成",
                "source": "llm",
            }
        )
        return section

    findings = data.get("findings")
    valid = 0
    for item in findings if isinstance(findings, list) else []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        detail = str(item.get("detail") or "").strip()
        if severity not in ("fail", "warn", "info") or not detail:
            continue
        if severity == "fail" and not strict:
            severity = "warn"
        valid += 1
        if valid <= _MAX_FINDINGS:
            section["issues"].append(
                {
                    "severity": severity,
                    "detail": detail[:300],
                    "evidence": str(item.get("evidence") or "")[:200],
                    "source": "llm",
                }
            )
    statuses = [i["severity"] for i in section["issues"]]
    if "fail" in statuses:
        section["status"] = "fail"
    elif "warn" in statuses:
        section["status"] = "warn"
    section["stats"] = {"findings": valid, "strict": strict}
    section["human_summary"] = str(data.get("summary_zh") or "").strip()[:600]
    return section
