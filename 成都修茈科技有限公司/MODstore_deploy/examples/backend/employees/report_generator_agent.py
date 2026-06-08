"""示例：报表 / 综述生成员工（可拷贝到 Mod 的 backend/employees/report_generator_agent.py）。

依赖宿主注入 ctx["call_llm"]；须保留模块级 SYSTEM_PROMPT 供工作台质检与 agent_runner 使用。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

SYSTEM_PROMPT = """你是 XCAGI Mod 内的「报表与综述生成」专职员工。

职责：
1. 根据用户在 payload 中给出的主题、数据片段与约束，产出可用于邮件、存档或二次排版的中文报告正文。
2. 默认使用 Markdown：必须有标题层级（## / ###）、要点列表、必要时表格；避免空话套话。
3. 若 payload 中数据不足，须在报告开头的「数据局限」中列出缺口，并给出可执行的补数建议，禁止捏造数值。
4. 若用户指定受众（如管理层 / 技术 / 运营），调整语气与详略；未指定时面向「业务读者」。
5. 输出内容必须可直接作为单个字段保存（不要外层 JSON、不要 ``` 围栏包裹全文）。

结构建议（可按任务删减）：
- 摘要（5～8 句）
- 关键发现（并列要点）
- 详细分析（可分节）
- 风险与假设
- 后续行动清单（含优先级）

语气：简洁、可执行、中文优先；术语首次出现可附简短英文。"""


def _extract_report_inputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 payload 抽取结构化字段，避免把原始 JSON 整体塞进 prompt（满足工作台「怎么做」提取逻辑）。"""
    p = payload or {}
    rows_in = p.get("rows")
    if not isinstance(rows_in, list):
        rows_in = p.get("data") if isinstance(p.get("data"), list) else []
    rows: List[Dict[str, Any]] = []
    for r in rows_in[:500]:
        if isinstance(r, dict):
            rows.append(r)
        elif isinstance(r, (list, tuple)):
            rows.append({"value": r})
        else:
            rows.append({"value": str(r)})

    metrics = p.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "task": str(p.get("task") or p.get("topic") or p.get("title") or "").strip(),
        "period": str(p.get("period") or p.get("date_range") or "").strip(),
        "audience": str(p.get("audience") or p.get("reader") or "").strip(),
        "format": str(p.get("format") or "markdown").strip().lower(),
        "constraints": str(p.get("constraints") or p.get("requirements") or "").strip(),
        "kpis": list(metrics.keys())[:40] if metrics else [],
        "sample_rows": rows[:20],
        "row_count": len(rows_in),
        "notes": str(p.get("notes") or p.get("context") or "").strip()[:4000],
    }


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    call_llm = ctx.get("call_llm")
    logger = ctx.get("logger")

    inputs = _extract_report_inputs(payload)
    if logger:
        logger.info(
            "[report_generator] task=%s period=%s rows=%s",
            inputs["task"][:120],
            inputs["period"],
            inputs["row_count"],
        )

    if not callable(call_llm):
        return {
            "summary": "ctx.call_llm 未注入，无法生成报告。",
            "report": "",
            "warnings": ["call_llm_missing"],
            "meta": inputs,
        }

    user_lines = [
        "请根据下列结构化输入生成完整报告正文（Markdown）。",
        f"任务/主题：{inputs['task'] or '（未命名任务）'}",
        f"统计周期：{inputs['period'] or '（未指定）'}",
        f"受众：{inputs['audience'] or '业务读者'}",
        f"格式偏好：{inputs['format']}",
    ]
    if inputs["constraints"]:
        user_lines.append(f"硬性约束：{inputs['constraints']}")
    if inputs["kpis"]:
        user_lines.append(f"指标键：{', '.join(inputs['kpis'])}")
    if inputs["notes"]:
        user_lines.append(f"补充说明：{inputs['notes']}")
    if inputs["sample_rows"]:
        user_lines.append("样例行（可用于表格或趋势描述）：")
        user_lines.append(json.dumps(inputs["sample_rows"], ensure_ascii=False)[:6000])
    elif inputs["row_count"]:
        user_lines.append(f"（共 {inputs['row_count']} 行数据，载荷中未包含明细行。）")

    user_msg = "\n".join(user_lines)

    res = await call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4096,
        temperature=0.35,
    )
    if not res.get("ok"):
        err = str(res.get("error") or "unknown")
        return {
            "summary": f"生成失败：{err[:400]}",
            "report": "",
            "warnings": ["call_llm_failed"],
            "meta": inputs,
        }

    body = str(res.get("content") or "").strip()
    lead = body.split("\n", 1)[0].strip() if body else ""
    return {
        "summary": lead[:500] if lead else body[:500],
        "report": body,
        "items": [],
        "warnings": [],
        "meta": inputs,
    }
