"""TXT 全量读取与 TXT 生成员工：检测、规则、兜底 convert 与包体验证。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

TXT_DOC_KEYWORDS = (
    ".txt",
    "txt",
    "纯文本",
    "文本文件",
    "text file",
    "plain text",
)
TXT_READ_ACTION_KEYWORDS = (
    "读取",
    "读出",
    "全量",
    "读入",
    "read",
    "load",
    "提取",
    "解析",
)
TXT_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写入",
    "写文档",
    "写 txt",
    "写txt",
    "输出",
    "改写",
    "润色",
    "write",
    "generate",
    "json",
    "结构化",
)
TXT_GENERATE_EXCLUDE = (
    "仅读取",
    "只读",
    "原样",
    "不要生成",
    "read only",
)

TXT_READ_OUTPUT_FIELDS = (
    "plain_text",
    "encoding",
    "line_count",
    "char_count",
    "source",
)
TXT_GENERATE_OUTPUT_FIELDS = (
    "lines",
    "paragraphs",
    "plain_text",
    "stats",
    "metadata",
)


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def _has_txt_doc_signal(bl: str) -> bool:
    if any(k in bl for k in TXT_DOC_KEYWORDS):
        return True
    if "文本" in bl and ("txt" in bl or "纯" in bl or "文件" in bl):
        return True
    return False


def _has_word_doc_signal(bl: str) -> bool:
    return any(k in bl for k in ("word", "docx", ".doc", "文档处理"))


def is_txt_generate(brief: str) -> bool:
    """上传 TXT → 读取 → JSON → 写 txt（含可选 LLM 润色）。"""
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate

    if is_pdf_full_read(brief) or is_pdf_generate(brief):
        return False
    bl = _brief_lower(brief)
    if any(k in bl for k in (".csv", "csv文件", "csv 文件")) and "csv" in bl:
        return False
    if not _has_txt_doc_signal(bl):
        return False
    if _has_word_doc_signal(bl) and any(k in bl for k in ("docx", "word", ".doc", "word文档")):
        return False
    if _has_word_doc_signal(bl) and not any(k in bl for k in (".txt", "txt文件", "txt 文件")):
        return False
    if any(k in bl for k in TXT_GENERATE_EXCLUDE) and not any(
        k in bl for k in TXT_GENERATE_ACTION_KEYWORDS
    ):
        return False
    return any(k in bl for k in TXT_GENERATE_ACTION_KEYWORDS)


def is_txt_full_read(brief: str) -> bool:
    """纯 TXT 全量读取，不走 Word 管线。"""
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate

    if is_txt_generate(brief) or is_pdf_full_read(brief) or is_pdf_generate(brief):
        return False
    bl = _brief_lower(brief)
    if any(k in bl for k in (".csv", "csv文件", "csv 文件")) and "csv" in bl:
        return False
    if not _has_txt_doc_signal(bl):
        return False
    if _has_word_doc_signal(bl):
        return False
    return any(k in bl for k in TXT_READ_ACTION_KEYWORDS)


def txt_read_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / TXT 全量读取",
        "goal": (brief or "").strip().splitlines()[0][:200] or "上传 .txt 并原样读出全部纯文本",
        "input": "用户上传的 .txt 文件",
        "output": "outputs/document_full.txt + outputs/document_meta.json",
        "output_schema": {
            "fields": list(TXT_READ_OUTPUT_FIELDS),
            "text_file": "outputs/document_full.txt",
            "meta_file": "outputs/document_meta.json",
        },
        "constraints": [
            "必须真实读取 txt 文件内容，禁止 LLM 编造正文",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["text.full_read", "text.encoding_detect"],
        "suggested_handlers": ["direct_python"],
    }


def txt_generate_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / TXT 生成",
        "goal": (brief or "").strip().splitlines()[0][:200] or "上传 TXT，结构化 JSON 并写出 txt",
        "input": "用户上传的 .txt 文件",
        "output": "outputs/document_parsed.json + outputs/generated_document.txt",
        "output_schema": {
            "fields": list(TXT_GENERATE_OUTPUT_FIELDS),
            "json_file": "outputs/document_parsed.json",
            "text_file": "outputs/generated_document.txt",
        },
        "constraints": [
            "必须真实读取 txt 并写出 JSON 与 txt",
            "direct_python 负责结构化与基础 txt；润色可选用 agent",
        ],
        "suggested_capabilities": ["text.parse", "text.write", "text.polish_optional"],
        "suggested_handlers": ["direct_python", "agent"],
    }


def build_txt_read_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/document_full.txt",
        "default_meta_relpath": "outputs/document_meta.json",
        "runtime_kind": "txt_full_read",
        "output_schema": list(TXT_READ_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Read .txt with utf-8-sig/utf-8/gb18030 fallback.",
            "Write document_full.txt (full plain text) and document_meta.json (metadata only).",
            "Never claim success unless output files are actually written.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def build_txt_generate_rule_spec(brief: str) -> Dict[str, Any]:
    bl = _brief_lower(brief)
    wants_polish = any(k in bl for k in ("润色", "改写", "生成正文", "polish", "rewrite"))
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/document_parsed.json",
        "default_text_output_relpath": "outputs/generated_document.txt",
        "runtime_kind": "txt_generate",
        "optional_llm_polish": wants_polish,
        "output_schema": list(TXT_GENERATE_OUTPUT_FIELDS),
        "requirements": [
            'handlers must include "direct_python"; may include "agent" for optional polish.',
            "Parse txt into lines/paragraphs JSON; write generated_document.txt from structured data.",
            "Never fabricate content when inputs/ is empty.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def _decode_text_bytes(data: bytes) -> Tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def render_txt_read_convert_module() -> str:
    return r"""from __future__ import annotations

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
    if suffix != ".txt":
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .txt")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "document_full.txt"
    if str(rule_spec.get("default_output_relpath") or "").endswith(".txt"):
        txt_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name
    meta_path = output_dir / "document_meta.json"
    if str(rule_spec.get("default_meta_relpath") or "").endswith(".json"):
        meta_path = output_dir / Path(str(rule_spec.get("default_meta_relpath"))).name

    raw = src_path.read_bytes()
    plain, encoding = _decode_bytes(raw)
    txt_path.write_bytes(plain.encode("utf-8"))
    lines = plain.splitlines()
    meta = {
        "plain_text": plain,
        "encoding": encoding,
        "line_count": len(lines),
        "char_count": len(plain),
        "source": src_path.name,
        "byte_size": len(raw),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(txt_path),
        "meta_output_path": str(meta_path),
        "line_count": len(lines),
        "char_count": len(plain),
        "encoding": encoding,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


def render_txt_generate_convert_module() -> str:
    return r"""from __future__ import annotations

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


def _paragraphs_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    paras: List[Dict[str, Any]] = []
    buf: List[str] = []
    for line in lines:
        if line.strip():
            buf.append(line)
        elif buf:
            paras.append({"text": "\n".join(buf), "line_span": len(buf)})
            buf = []
    if buf:
        paras.append({"text": "\n".join(buf), "line_span": len(buf)})
    if not paras and lines:
        paras.append({"text": "\n".join(lines), "line_span": len(lines)})
    return paras


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
    if suffix != ".txt":
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .txt")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "document_parsed.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    gen_txt_path = output_dir / "generated_document.txt"
    if str(rule_spec.get("default_text_output_relpath") or "").endswith(".txt"):
        gen_txt_path = output_dir / Path(str(rule_spec.get("default_text_output_relpath"))).name

    raw = src_path.read_bytes()
    plain, encoding = _decode_bytes(raw)
    lines = plain.splitlines()
    paragraphs = _paragraphs_from_lines(lines)
    payload_data: Dict[str, Any] = {
        "metadata": {"source": src_path.name, "format": "txt", "encoding": encoding},
        "lines": [{"index": i, "text": ln} for i, ln in enumerate(lines)],
        "paragraphs": paragraphs,
        "plain_text": plain,
        "stats": {
            "line_count": len(lines),
            "paragraph_count": len(paragraphs),
            "char_count": len(plain),
            "byte_size": len(raw),
        },
    }
    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8")
    header = f"# Generated from {src_path.name}\n\n"
    body = plain if plain.endswith("\n") else plain + "\n"
    gen_txt_path.write_bytes((header + body).encode("utf-8"))

    stats = payload_data.get("stats") or {}
    return {
        "output_path": str(json_path),
        "text_output_path": str(gen_txt_path),
        "line_count": stats.get("line_count", 0),
        "paragraph_count": stats.get("paragraph_count", 0),
        "char_count": stats.get("char_count", 0),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


def validate_txt_read_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_txt_backend(
        pack_dir, runtime_kind="txt_full_read", required_tokens=("document_full", ".txt")
    )


def validate_txt_generate_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_txt_backend(
        pack_dir,
        runtime_kind="txt_generate",
        required_tokens=("document_parsed", "generated_document"),
    )


def _validate_txt_backend(
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
    if runtime_kind == "txt_generate" and handlers and "agent" not in handlers:
        rs_path = pack_dir / "rule_spec.json"
        if rs_path.is_file():
            try:
                rs = json.loads(rs_path.read_text(encoding="utf-8"))
                if isinstance(rs, dict) and rs.get("optional_llm_polish"):
                    warnings.append("声明 optional_llm_polish 但 handlers 未含 agent")
            except (OSError, json.JSONDecodeError):
                pass
    if not has_convert:
        errors.append("backend/vendor 中缺少 convert_file 实现")
    if ".txt" not in py_blob and "read_bytes" not in py_blob and "read_text" not in py_blob:
        warnings.append("未发现 txt 读取相关代码")
    for tok in required_tokens:
        if tok.lower() not in py_blob:
            warnings.append(f"convert 模块可能未覆盖：{tok}")

    return errors, warnings


def minimal_txt_fixture_bytes(content: str = "smoke txt line\nsecond line\n") -> bytes:
    return content.encode("utf-8")


def txt_read_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "TXT 全量读取员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ 中 .txt，原样写入 outputs/document_full.txt；"
        "元数据写入 outputs/document_meta.json；无输入时写 outputs/readme.md。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n" "员工必须使用 direct_python 真实读取 txt，禁止 LLM 编造正文。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "只能读 inputs/、写 outputs/；禁止联网。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{merged or clean}\n\nSkill：上传 txt → 全量读取 → 交付 document_full.txt。",
        "acceptance": [
            "handlers 为 direct_python",
            "输出 document_full.txt 与源文件一致",
            "document_meta.json 仅含元数据",
        ],
    }


def txt_generate_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "TXT 生成员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ .txt → 结构化 JSON（lines/paragraphs/stats）→ "
        "写入 outputs/document_parsed.json 与 outputs/generated_document.txt。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n"
            "direct_python 负责解析与写文件；用户要求润色/改写时可走 agent，禁止无输入编造。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "direct_python 读写在先；agent 仅用于可选润色。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": (
            f"{merged or clean}\n\nSkill：上传 → 读取 → JSON → 写 generated txt → 可选润色。"
        ),
        "acceptance": [
            "输出 document_parsed.json 含 lines/paragraphs/stats",
            "输出 generated_document.txt",
            "handlers 含 direct_python，可选 agent",
        ],
    }


def resolve_txt_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if is_txt_generate(brief):
        return txt_generate_orchestration_plan(brief, payload)
    return txt_read_orchestration_plan(brief, payload)
