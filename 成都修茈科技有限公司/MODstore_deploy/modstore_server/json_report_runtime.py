"""JSON → HTML 量化报告 runtime（办公员工拓展：json-report-employee）。"""

from __future__ import annotations

import asyncio
import json
import re
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

JSON_REPORT_OUTPUT_FIELDS = (
    "report_html_path",
    "paragraph_count",
    "table_count",
    "outline_nodes",
    "source_title",
)

_JSON_REPORT_KEYWORDS = (
    "json-report",
    "json_report",
    "json-report-employee",
    "json report",
    "量化报告",
    "json转报告",
    "json 转报告",
    "document_full",
    "execute_result",
)
_JSON_REPORT_EXCLUDE = (
    "word-generate",
    "ppt-generate",
    "excel-generate",
    "全量读取",
    "full-read",
    "full_read",
    "extract",
    "提取",
)


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def is_json_quant_report(brief: str) -> bool:
    bl = _brief_lower(brief)
    if "json-report-employee" in bl or "json_report_employee" in bl:
        return True
    if any(k in bl for k in _JSON_REPORT_EXCLUDE):
        return False
    if not any(k in bl for k in _JSON_REPORT_KEYWORDS):
        return False
    return any(
        k in bl
        for k in (
            "量化报告",
            "json转报告",
            "json 转报告",
            "json report",
            "json-report",
            "报告员",
            "html 报告",
        )
    )


def build_json_quant_report_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".json"],
        "default_action": "convert",
        "default_output_relpath": "outputs/quantitative_report.html",
        "runtime_kind": "json_quant_report",
        "output_schema": list(JSON_REPORT_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Load document_full.json or execute_result wrapper JSON.",
            "Generate outputs/quantitative_report.html via ctx.call_llm; never fabricate facts.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
        "pack_id": "json-report-employee",
    }


def normalize_document_payload(data: Any) -> Dict[str, Any]:
    """Extract document_full-shaped dict from raw JSON or execute_result wrapper."""
    if not isinstance(data, dict):
        raise ValueError("JSON 根须为对象")

    if isinstance(data.get("paragraphs"), list) or isinstance(data.get("tables"), list):
        return data

    for key in ("document_full", "document", "doc"):
        nested = data.get(key)
        if isinstance(nested, dict) and (
            isinstance(nested.get("paragraphs"), list) or isinstance(nested.get("plain_text"), str)
        ):
            return nested

    result = data.get("result")
    if isinstance(result, dict):
        try:
            return normalize_document_payload(result)
        except ValueError:
            pass
        outputs = result.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                out = item.get("output")
                if isinstance(out, dict):
                    try:
                        return normalize_document_payload(out)
                    except ValueError:
                        continue
                for path_key in ("output_path", "json_path", "document_json_path"):
                    p = out.get(path_key) if isinstance(out, dict) else None
                    if p and str(p).endswith(".json"):
                        raise ValueError(f"嵌套 JSON 路径需在工作区内已解析: {p}")

    plain = data.get("plain_text")
    if isinstance(plain, str) and plain.strip():
        return {
            "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            "paragraphs": [{"index": 0, "text": plain[:50000], "is_heading": False}],
            "tables": [],
            "outline": [],
            "plain_text": plain,
        }

    raise ValueError(
        "无法识别 JSON：请上传 document_full.json（Word 全量读取产出）或含 paragraphs/tables 的对象"
    )


def build_quant_summary(
    doc: Dict[str, Any], *, max_outline: int = 24, max_tables: int = 8
) -> Dict[str, Any]:
    paragraphs = doc.get("paragraphs") if isinstance(doc.get("paragraphs"), list) else []
    tables = doc.get("tables") if isinstance(doc.get("tables"), list) else []
    outline = doc.get("outline") if isinstance(doc.get("outline"), list) else []

    headings: List[Dict[str, Any]] = []
    for p in paragraphs[:500]:
        if not isinstance(p, dict):
            continue
        if p.get("is_heading") or (p.get("heading_level") and int(p.get("heading_level") or 0) > 0):
            headings.append(
                {
                    "level": int(p.get("heading_level") or 1),
                    "text": str(p.get("text") or "")[:200],
                    "index": p.get("index"),
                }
            )
        if len(headings) >= max_outline:
            break

    table_stats: List[Dict[str, Any]] = []
    for t in tables[:max_tables]:
        if not isinstance(t, dict):
            continue
        rows = t.get("rows") if isinstance(t.get("rows"), list) else []
        table_stats.append(
            {
                "index": t.get("index"),
                "row_count": t.get("row_count") or len(rows),
                "col_count": t.get("col_count")
                or (len(rows[0]) if rows and isinstance(rows[0], list) else 0),
                "preview_rows": rows[:3] if rows else [],
            }
        )

    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    core = doc.get("core_properties") if isinstance(doc.get("core_properties"), dict) else {}
    title = (
        str(meta.get("title") or core.get("title") or core.get("dc:title") or "").strip()
        or str(headings[0]["text"] if headings else "")[:120]
        or "未命名文档"
    )

    plain = str(doc.get("plain_text") or "")[:8000]
    excerpt_paras: List[str] = []
    for p in paragraphs[:40]:
        if isinstance(p, dict):
            t = str(p.get("text") or "").strip()
            if t and len(t) > 2:
                excerpt_paras.append(t[:400])

    return {
        "title": title,
        "paragraph_count": len(paragraphs),
        "table_count": len(tables),
        "outline_node_count": len(outline) or len(headings),
        "headings": headings[:max_outline],
        "table_stats": table_stats,
        "plain_text_excerpt": plain[:6000],
        "paragraph_excerpts": excerpt_paras[:20],
        "metadata": meta,
        "core_properties": {k: str(v)[:200] for k, v in list(core.items())[:12]},
    }


def build_report_prompt(
    doc: Dict[str, Any], summary: Dict[str, Any], task: str
) -> List[Dict[str, str]]:
    stats_json = json.dumps(summary, ensure_ascii=False, indent=2)
    system = (
        "你是企业文档量化报告撰写专家。根据用户提供的结构化 JSON 摘要生成一份美观、专业的中文 HTML 量化报告。\n"
        "硬性规则：\n"
        "1. 只输出完整 HTML 文档（以 <!DOCTYPE html> 开头），不要 markdown 代码围栏。\n"
        "2. 仅使用摘要与节选中出现的事实与数字；禁止编造不存在的章节、指标或结论。\n"
        "3. 内嵌 CSS（<style>），深色/浅色均可，需含：封面区、执行摘要、关键指标卡片、目录结构表、表格摘要、附录说明。\n"
        "4. 数字指标优先引用 summary 中的 paragraph_count、table_count、headings、table_stats。\n"
        "5. 若信息不足，在报告中明确标注「原文未提供」。"
    )
    user = (
        f"任务：{task or '生成量化分析报告'}\n\n"
        f"## 确定性统计摘要（可信）\n```json\n{stats_json}\n```\n\n"
        "请基于以上数据生成 quantitative_report.html 的完整 HTML 源码。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_html_from_llm_content(content: str) -> str:
    raw = (content or "").strip()
    if not raw:
        return ""
    fence = re.search(r"```(?:html)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    if "<!DOCTYPE" in raw.upper() or "<html" in raw.lower():
        start = raw.upper().find("<!DOCTYPE")
        if start < 0:
            start = raw.lower().find("<html")
        return raw[start:].strip()
    return raw


def _fallback_html(summary: Dict[str, Any], *, warning: str = "") -> str:
    title = escape(str(summary.get("title") or "量化报告"))
    rows = "".join(
        f"<tr><td>{escape(str(h.get('level')))}</td><td>{escape(str(h.get('text')))}</td></tr>"
        for h in (summary.get("headings") or [])[:20]
    )
    warn = f"<p class='warn'>{escape(warning)}</p>" if warning else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#0f1419;color:#e6edf3;line-height:1.6}}
.wrap{{max-width:920px;margin:0 auto;padding:32px 20px}}
h1{{font-size:1.75rem;margin:0 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}}
.card{{background:#1a2332;border-radius:12px;padding:16px;border:1px solid #2d3a4f}}
.card b{{display:block;font-size:1.5rem;color:#58a6ff}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}
th,td{{border:1px solid #2d3a4f;padding:8px 10px;text-align:left}}
th{{background:#1a2332}}
.warn{{color:#f0883e}}
</style>
</head>
<body><div class="wrap">
<h1>{title}</h1>
<p>自动生成量化报告（LLM 不可用时的降级版）</p>
{warn}
<div class="cards">
<div class="card"><span>段落数</span><b>{summary.get("paragraph_count", 0)}</b></div>
<div class="card"><span>表格数</span><b>{summary.get("table_count", 0)}</b></div>
<div class="card"><span>大纲节点</span><b>{summary.get("outline_node_count", 0)}</b></div>
</div>
<h2>文档结构</h2>
<table><thead><tr><th>层级</th><th>标题</th></tr></thead><tbody>{rows or "<tr><td colspan='2'>无</td></tr>"}</tbody></table>
</div></body></html>"""


async def generate_report_html(
    doc: Dict[str, Any],
    summary: Dict[str, Any],
    task: str,
    ctx: Dict[str, Any],
    *,
    max_tokens: int = 10000,
    payload: Optional[Dict[str, Any]] = None,
    llm_timeout_s: float = 90.0,
) -> tuple[str, List[str]]:
    warnings: List[str] = []
    payload = payload or {}
    if payload.get("skip_llm"):
        warnings.append("已按请求跳过 LLM，使用降级 HTML 模板")
        return _fallback_html(summary, warning="; ".join(warnings)), warnings

    messages = build_report_prompt(doc, summary, task)
    call_llm = ctx.get("call_llm")
    html = ""
    if callable(call_llm):
        try:
            res = await asyncio.wait_for(
                call_llm(messages, max_tokens=max_tokens, temperature=0.2),
                timeout=float(payload.get("llm_timeout_s") or llm_timeout_s),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"LLM 调用失败: {exc}")
            res = None
        if isinstance(res, dict) and res.get("ok"):
            html = _extract_html_from_llm_content(str(res.get("content") or ""))
        elif isinstance(res, dict):
            warnings.append(str(res.get("error") or "LLM 返回失败")[:400])
    else:
        warnings.append("ctx.call_llm 不可用，使用降级 HTML 模板")

    if not html or "<html" not in html.lower():
        warnings.append("LLM 未返回有效 HTML，已使用降级模板")
        html = _fallback_html(summary, warning="; ".join(warnings))
    return html, warnings


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    del template_path
    if src_path.suffix.lower() != ".json":
        raise ValueError(f"不支持的文件类型：{src_path.suffix}，仅支持 .json")

    raw = json.loads(src_path.read_text(encoding="utf-8"))
    doc = normalize_document_payload(raw)
    summary = build_quant_summary(doc)
    task = str(payload.get("task") or "生成 JSON 量化报告")
    max_tokens = int(payload.get("max_tokens") or rule_spec.get("max_tokens") or 10000)

    html, warnings = await generate_report_html(
        doc, summary, task, ctx, max_tokens=max_tokens, payload=payload
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() != ".html":
        output_path = output_path.parent / "quantitative_report.html"
    output_path.write_text(html, encoding="utf-8")

    brief_md = output_path.parent / "report_brief.md"
    try:
        brief_md.write_text(
            f"# {summary.get('title')}\n\n"
            f"- 段落: {summary.get('paragraph_count')}\n"
            f"- 表格: {summary.get('table_count')}\n",
            encoding="utf-8",
        )
    except OSError:
        warnings.append("report_brief.md 写入跳过")

    return {
        "output_path": str(output_path),
        "report_html_path": str(output_path),
        "paragraph_count": summary.get("paragraph_count"),
        "table_count": summary.get("table_count"),
        "outline_nodes": summary.get("outline_node_count"),
        "source_title": summary.get("title"),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }


def render_json_report_convert_module() -> str:
    return r"""from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.json_report_runtime import convert_file as _convert_file


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    return await _convert_file(
        src_path,
        output_path,
        template_path=template_path,
        payload=payload,
        ctx=ctx,
        rule_spec=rule_spec,
    )
"""
