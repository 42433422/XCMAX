"""CSV 全量读取与 CSV 生成员工：检测、规则、兜底 convert 与包体验证（JSON 为中介）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

CSV_DOC_KEYWORDS = (
    ".csv",
    "csv",
    "逗号分隔",
    "表格数据",
)
CSV_READ_ACTION_KEYWORDS = (
    "读取",
    "读出",
    "读入",
    "解析",
    "提取",
    "导入",
    "read",
    "parse",
    "load",
    "import",
)
CSV_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写出",
    "导出",
    "写入",
    "写csv",
    "写 csv",
    "转为csv",
    "转成csv",
    "写出csv",
    "写出 csv",
    "write",
    "generate",
    "export",
)
CSV_GENERATE_EXCLUDE = (
    "仅读取",
    "只读",
    "不要生成",
    "read only",
)

CSV_READ_OUTPUT_FIELDS = (
    "columns",
    "rows",
    "row_count",
    "meta",
)
CSV_GENERATE_OUTPUT_FIELDS = (
    "columns",
    "rows",
    "row_count",
    "delimiter",
    "encoding",
)


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def _has_csv_signal(bl: str) -> bool:
    return any(k in bl for k in CSV_DOC_KEYWORDS)


def is_csv_generate(brief: str) -> bool:
    """JSON 中介 → 写出 .csv。"""
    bl = _brief_lower(brief)
    if not _has_csv_signal(bl):
        return False
    if any(k in bl for k in CSV_GENERATE_EXCLUDE) and not any(
        k in bl for k in CSV_GENERATE_ACTION_KEYWORDS
    ):
        return False
    return any(k in bl for k in CSV_GENERATE_ACTION_KEYWORDS)


def is_csv_full_read(brief: str) -> bool:
    """上传 .csv → 结构化 JSON（data.json）。"""
    if is_csv_generate(brief):
        return False
    bl = _brief_lower(brief)
    if not _has_csv_signal(bl):
        return False
    return any(k in bl for k in CSV_READ_ACTION_KEYWORDS)


def csv_read_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "数据处理 / CSV 全量读取",
        "goal": (brief or "").strip().splitlines()[0][:200]
        or "上传 .csv 并输出 JSON 中介 data.json",
        "input": "用户上传的 .csv 文件",
        "output": "outputs/data.json（columns、rows、row_count、meta）",
        "output_schema": {
            "fields": list(CSV_READ_OUTPUT_FIELDS),
            "json_file": "outputs/data.json",
        },
        "constraints": [
            "必须真实解析 csv，禁止 LLM 编造行列",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["data.csv_read", "data.json_export"],
        "suggested_handlers": ["direct_python"],
    }


def csv_generate_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "数据处理 / CSV 生成",
        "goal": (brief or "").strip().splitlines()[0][:200] or "JSON 中介 → 写出 output.csv",
        "input": "用户上传的 .json 或 run payload 中的结构化数据",
        "output": "outputs/output.csv",
        "output_schema": {
            "fields": list(CSV_GENERATE_OUTPUT_FIELDS),
            "csv_file": "outputs/output.csv",
        },
        "constraints": [
            "必须根据 JSON 的 columns/rows 真实写出 csv",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["data.json_read", "data.csv_write"],
        "suggested_handlers": ["direct_python"],
    }


def build_csv_read_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".csv"],
        "default_action": "convert",
        "default_output_relpath": "outputs/data.json",
        "runtime_kind": "csv_full_read",
        "output_schema": list(CSV_READ_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Parse .csv with csv.DictReader; write outputs/data.json.",
            "JSON must include columns, rows, row_count, meta (delimiter, encoding, source).",
            "Never claim success unless data.json is actually written.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def build_csv_generate_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".json", ".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/output.csv",
        "runtime_kind": "csv_generate",
        "output_schema": list(CSV_GENERATE_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Read JSON / user_query 纯文本 / .txt; write outputs/output.csv via csv.DictWriter.",
            "Support payload.table_json; optional LLM structures plain text.",
            "Never fabricate rows when inputs/ is empty and payload has no table.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def render_csv_read_convert_module() -> str:
    return r"""from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    suffix = src_path.suffix.lower()
    if suffix != ".csv":
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .csv")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".json"):
        json_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    raw_bytes = src_path.read_bytes()
    text, encoding = _decode_bytes(raw_bytes)
    delimiter = _sniff_delimiter(text)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows: List[Dict[str, Any]] = [dict(r) for r in reader]
    columns = list(reader.fieldnames or [])
    if not columns and rows:
        columns = list(rows[0].keys())

    payload_data: Dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "meta": {
            "source": src_path.name,
            "delimiter": delimiter,
            "encoding": encoding,
            "byte_size": len(raw_bytes),
        },
    }
    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(json_path),
        "row_count": len(rows),
        "column_count": len(columns),
        "delimiter": delimiter,
        "encoding": encoding,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


def render_csv_generate_convert_module() -> str:
    return r"""from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.office_plaintext_generate import resolve_table_spec


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    table, _warnings = await resolve_table_spec(src_path, payload or {}, ctx or {}, rule_spec or {}, fmt="csv")
    columns = [str(c) for c in (table.get("columns") or []) if str(c).strip()]
    rows_in = table.get("rows")
    if not isinstance(rows_in, list):
        raise ValueError("JSON 缺少 rows 数组")
    if not columns and rows_in and isinstance(rows_in[0], dict):
        columns = [str(k) for k in rows_in[0].keys()]

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "output.csv"
    if output_path.suffix.lower() == ".csv":
        csv_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".csv"):
        csv_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    delimiter = str((table.get("meta") or {}).get("delimiter") or payload.get("delimiter") or ",")
    encoding = "utf-8-sig"
    with csv_path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=delimiter)
        writer.writeheader()
        for row in rows_in:
            if isinstance(row, dict):
                writer.writerow({k: row.get(k, "") for k in columns})

    return {
        "output_path": str(csv_path),
        "row_count": len(rows_in),
        "column_count": len(columns),
        "delimiter": delimiter,
        "encoding": encoding,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


def validate_csv_read_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_csv_backend(
        pack_dir,
        runtime_kind="csv_full_read",
        required_tokens=("data.json", "dictreader", "columns"),
    )


def validate_csv_generate_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_csv_backend(
        pack_dir,
        runtime_kind="csv_generate",
        required_tokens=("output.csv", "dictwriter", "columns"),
    )


def _validate_csv_backend(
    pack_dir: Path,
    *,
    runtime_kind: str,
    required_tokens: tuple[str, ...],
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    backend = pack_dir / "backend"
    if not backend.is_dir():
        errors.append("缺少 backend 目录")
        return errors, warnings

    py_blob = ""
    has_convert = False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            py_blob += text.lower()
            if "def convert_file" in text and "vendor" in str(py_path).lower():
                has_convert = True
        except OSError:
            pass

    mf_path = pack_dir / "manifest.json"
    handlers: List[str] = []
    if mf_path.is_file():
        try:
            from modstore_server.employee_asset_pipeline import manifest_actions_handlers

            mf = json.loads(mf_path.read_text(encoding="utf-8"))
            handlers = manifest_actions_handlers(mf)
        except (json.JSONDecodeError, OSError):
            warnings.append("manifest.json 无法解析")

    if handlers and "direct_python" not in handlers:
        errors.append(f"{runtime_kind} 员工 handlers 必须包含 direct_python")
    if not has_convert:
        errors.append("backend/vendor 中缺少 convert_file 实现")
    if "csv" not in py_blob and "dictreader" not in py_blob and "dictwriter" not in py_blob:
        warnings.append("未发现 csv 模块相关代码")
    for tok in required_tokens:
        if tok.lower() not in py_blob:
            warnings.append(f"convert 模块可能未覆盖：{tok}")

    rs_path = pack_dir / "rule_spec.json"
    if rs_path.is_file():
        try:
            rs = json.loads(rs_path.read_text(encoding="utf-8"))
            if isinstance(rs, dict) and rs.get("runtime_kind") != runtime_kind:
                warnings.append(f"rule_spec.runtime_kind 期望 {runtime_kind}")
        except (OSError, json.JSONDecodeError):
            warnings.append("rule_spec.json 无法解析")

    return errors, warnings


def minimal_csv_fixture_bytes() -> bytes:
    return "name,score\nalice,90\nbob,85\n".encode("utf-8")


def minimal_csv_table_json() -> Dict[str, Any]:
    return {
        "columns": ["name", "score"],
        "rows": [{"name": "alice", "score": "90"}, {"name": "bob", "score": "85"}],
        "row_count": 2,
        "meta": {"delimiter": ",", "encoding": "utf-8", "source": "fixture"},
    }


def minimal_json_fixture_bytes() -> bytes:
    return json.dumps(minimal_csv_table_json(), ensure_ascii=False, indent=2).encode("utf-8")


def csv_read_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    short = "CSV 全量读取员"
    return {
        "employee_name": short,
        "employee_brief": (
            f"{clean}\n\n"
            "员工必须使用 direct_python 将 .csv 解析为 outputs/data.json（JSON 中介），禁止编造行列。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": f"{clean}\n\n读取 inputs/*.csv，写出 outputs/data.json。",
        "script_runtime_notes": "只能读 inputs/、写 outputs/；使用 csv 标准库。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{clean}\n\nSkill：上传 csv → DictReader → data.json。",
        "acceptance": [
            "handlers 为 direct_python",
            "data.json 含 columns、rows、row_count",
        ],
    }


def csv_generate_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    short = "CSV 生成员"
    return {
        "employee_name": short,
        "employee_brief": (
            f"{clean}\n\n"
            "员工必须使用 direct_python 从 JSON（columns/rows）写出 outputs/output.csv，禁止编造数据。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": f"{clean}\n\n读取 inputs/*.json，写出 outputs/output.csv。",
        "script_runtime_notes": "JSON 为中介；使用 csv.DictWriter。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{clean}\n\nSkill：JSON → CSV 落盘。",
        "acceptance": [
            "handlers 为 direct_python",
            "output.csv 列与 JSON columns 一致",
        ],
    }


def resolve_csv_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if is_csv_generate(brief):
        return csv_generate_orchestration_plan(brief, payload)
    return csv_read_orchestration_plan(brief, payload)
