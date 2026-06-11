"""Kitten 数据集 → ECharts 可视化（办公员工附属包1：chart-*-employee）。"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KITTEN_CHART_OUTPUT_FIELDS = (
    "chart_spec_path",
    "chart_html_path",
    "chart_type",
    "row_count",
    "column_count",
)

_CHART_EMPLOYEES: Dict[str, str] = {
    "chart-bar-employee": "bar",
    "chart-line-employee": "line",
    "chart-pie-employee": "pie",
    "chart-dashboard-employee": "dashboard",
}


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def resolve_kitten_chart_type(brief: str, pack_id: str = "") -> str:
    pid = (pack_id or "").strip()
    if pid in _CHART_EMPLOYEES:
        return _CHART_EMPLOYEES[pid]
    bl = _brief_lower(brief)
    for key, ctype in _CHART_EMPLOYEES.items():
        if key.replace("-", "_") in bl or key in bl:
            return ctype
    if "折线" in brief or "line" in bl:
        return "line"
    if "饼" in brief or "pie" in bl:
        return "pie"
    if "看板" in brief or "dashboard" in bl:
        return "dashboard"
    return "bar"


def is_kitten_chart_viz(brief: str) -> bool:
    bl = _brief_lower(brief)
    if any(k.replace("-", "_") in bl or k in bl for k in _CHART_EMPLOYEES):
        return True
    if "chart-" in bl and "employee" in bl:
        return True
    return any(k in bl for k in ("可视化员", "kitten chart", "kitten_chart", "小猫分析", "echarts"))


def build_kitten_chart_rule_spec(brief: str) -> Dict[str, Any]:
    pack_id = ""
    for key in _CHART_EMPLOYEES:
        if key in brief or key.replace("-", "_") in _brief_lower(brief):
            pack_id = key
            break
    chart_type = resolve_kitten_chart_type(brief, pack_id)
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".json", ".csv"],
        "default_action": "convert",
        "default_output_relpath": "outputs/chart_spec.json",
        "runtime_kind": "kitten_chart_viz",
        "chart_type": chart_type,
        "output_schema": list(KITTEN_CHART_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Load kitten dataset JSON (columns/rows) or CSV converted to rows.",
            "Generate outputs/chart_spec.json and outputs/chart.html; never fabricate data.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
        "pack_id": pack_id or f"chart-{chart_type}-employee",
    }


def _load_dataset(src_path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    suffix = src_path.suffix.lower()
    if suffix == ".csv":
        import csv

        with src_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            columns = list(reader.fieldnames or [])
            rows = [dict(r) for r in reader]
        return columns, rows
    data = json.loads(src_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根须为对象")
    if isinstance(data.get("rows"), list):
        columns = [str(c) for c in (data.get("columns") or [])]
        if not columns and data["rows"]:
            first = data["rows"][0]
            if isinstance(first, dict):
                columns = list(first.keys())
        rows = [r for r in data["rows"] if isinstance(r, dict)]
        return columns, rows
    if isinstance(data.get("dataset"), dict):
        nested = data["dataset"]
        columns = [str(c) for c in (nested.get("columns") or nested.get("fieldNames") or [])]
        rows = [r for r in (nested.get("rows") or []) if isinstance(r, dict)]
        return columns, rows
    raise ValueError("未识别 kitten 数据集结构（需 columns/rows 或 dataset）")


def _pick_fields(columns: List[str], rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    if not columns or not rows:
        return "", ""
    numeric_scores: Dict[str, int] = {c: 0 for c in columns}
    for row in rows[:200]:
        for col in columns:
            val = row.get(col)
            if isinstance(val, (int, float)):
                numeric_scores[col] += 1
                continue
            if isinstance(val, str):
                cleaned = val.replace(",", "").replace("，", "").strip()
                try:
                    float(cleaned)
                    numeric_scores[col] += 1
                except ValueError:
                    pass
    y_field = max(numeric_scores, key=lambda k: numeric_scores[k]) if numeric_scores else ""
    if numeric_scores.get(y_field, 0) == 0:
        y_field = ""
    x_field = next((c for c in columns if c != y_field), columns[0])
    return x_field, y_field


def _aggregate_rows(
    rows: List[Dict[str, Any]], x_field: str, y_field: str
) -> Tuple[List[str], List[float]]:
    bucket: Dict[str, List[float]] = {}
    for row in rows:
        label = str(row.get(x_field) or "空值").strip() or "空值"
        if y_field:
            raw = row.get(y_field)
            num: Optional[float] = None
            if isinstance(raw, (int, float)):
                num = float(raw)
            elif isinstance(raw, str):
                try:
                    num = float(raw.replace(",", "").replace("，", "").strip())
                except ValueError:
                    num = None
            if num is None:
                continue
            bucket.setdefault(label, []).append(num)
        else:
            bucket.setdefault(label, []).append(1.0)
    labels = list(bucket.keys())[:24]
    values = [sum(bucket[l]) / len(bucket[l]) if bucket[l] else 0 for l in labels]
    return labels, values


def build_chart_spec(
    chart_type: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
    *,
    title: str = "小猫分析 · 可视化",
) -> Dict[str, Any]:
    x_field, y_field = _pick_fields(columns, rows)
    labels, values = _aggregate_rows(rows, x_field, y_field)
    base = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis" if chart_type != "pie" else "item"},
        "xField": x_field,
        "yField": y_field or "count",
        "rowCount": len(rows),
    }
    if chart_type == "pie":
        return {
            **base,
            "series": [
                {
                    "type": "pie",
                    "radius": ["36%", "68%"],
                    "data": [{"name": l, "value": v} for l, v in zip(labels, values)],
                }
            ],
        }
    if chart_type == "line":
        return {
            **base,
            "xAxis": {"type": "category", "data": labels},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "smooth": True, "data": values, "areaStyle": {"opacity": 0.08}}],
        }
    if chart_type == "dashboard":
        pie_spec = build_chart_spec("pie", columns, rows, title="结构占比")
        bar_spec = build_chart_spec("bar", columns, rows, title="分类对比")
        line_spec = build_chart_spec("line", columns, rows, title="趋势走势")
        return {
            "dashboard": True,
            "panels": [
                {"id": "kpi", "kind": "kpi", "value": len(rows), "label": "样本行数"},
                {"id": "bar", "kind": "chart", "spec": bar_spec},
                {"id": "line", "kind": "chart", "spec": line_spec},
                {"id": "pie", "kind": "chart", "spec": pie_spec},
            ],
        }
    return {
        **base,
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": values, "barMaxWidth": 48}],
    }


def render_chart_html(spec: Dict[str, Any], *, title: str = "小猫分析 · 可视化") -> str:
    spec_json = json.dumps(spec, ensure_ascii=False)
    safe_title = escape(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{safe_title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; }}
    .wrap {{ max-width: 960px; margin: 0 auto; padding: 24px; }}
    .panel {{ background: #fff; border-radius: 12px; box-shadow: 0 8px 24px rgba(15,23,42,.06); margin-bottom: 16px; padding: 12px; }}
    .chart {{ width: 100%; height: 360px; }}
    .kpi {{ font-size: 32px; font-weight: 700; color: #1e293b; }}
    .kpi-label {{ color: #64748b; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{safe_title}</h1>
    <div id="root"></div>
  </div>
  <script>
    const spec = {spec_json};
    const root = document.getElementById('root');
    if (spec.dashboard && Array.isArray(spec.panels)) {{
      spec.panels.forEach((panel, idx) => {{
        const box = document.createElement('div');
        box.className = 'panel';
        if (panel.kind === 'kpi') {{
          box.innerHTML = '<div class="kpi">' + panel.value + '</div><div class="kpi-label">' + (panel.label || '') + '</div>';
        }} else if (panel.kind === 'chart' && panel.spec) {{
          const el = document.createElement('div');
          el.className = 'chart';
          el.id = 'chart-' + idx;
          box.appendChild(el);
          root.appendChild(box);
          const chart = echarts.init(el);
          chart.setOption(panel.spec);
          return;
        }}
        root.appendChild(box);
      }});
    }} else {{
      const el = document.createElement('div');
      el.className = 'chart panel';
      el.style.height = '420px';
      root.appendChild(el);
      const chart = echarts.init(el);
      chart.setOption(spec);
    }}
  </script>
</body>
</html>"""


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    del template_path, payload
    columns, rows = _load_dataset(src_path)
    chart_type = str(rule_spec.get("chart_type") or resolve_kitten_chart_type(rule_spec.get("brief") or ""))
    pack_id = str(rule_spec.get("pack_id") or "")
    title_map = {
        "chart-bar-employee": "柱状图 · 分类对比",
        "chart-line-employee": "折线图 · 趋势分析",
        "chart-pie-employee": "饼图 · 结构占比",
        "chart-dashboard-employee": "综合看板 · 多图联动",
    }
    title = title_map.get(pack_id, "小猫分析 · 可视化")
    spec = build_chart_spec(chart_type, columns, rows, title=title)
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "chart_spec.json"
    html_path = out_dir / "chart.html"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_chart_html(spec, title=title), encoding="utf-8")
    return {
        "output_path": str(spec_path),
        "chart_spec_path": str(spec_path),
        "chart_html_path": str(html_path),
        "chart_type": chart_type,
        "row_count": len(rows),
        "column_count": len(columns),
        "warnings": [],
        "output_schema": list(rule_spec.get("output_schema") or []),
    }


def render_kitten_chart_convert_module() -> str:
    return r"""from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.kitten_chart_runtime import convert_file as _convert_file


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
