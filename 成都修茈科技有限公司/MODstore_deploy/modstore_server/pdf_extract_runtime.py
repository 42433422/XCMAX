"""PDF 全量读取与 PDF 生成员工：检测、规则、兜底 convert 与包体验证。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modstore_server.pdf_extract_templates import (
    render_pdf_generate_convert_module as render_pdf_generate_convert_module,
)
from modstore_server.pdf_extract_templates import (
    render_pdf_read_convert_module as render_pdf_read_convert_module,
)

PDF_DOC_KEYWORDS = (
    ".pdf",
    "pdf",
    "便携式文档",
    "pdf文件",
    "pdf 文件",
)
PDF_READ_ACTION_KEYWORDS = (
    "读取",
    "读出",
    "全量",
    "读入",
    "read",
    "load",
    "提取",
    "解析",
    "原生",
    "文字",
)
PDF_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写入",
    "写 pdf",
    "写pdf",
    "输出",
    "改写",
    "润色",
    "write",
    "generate",
    "json",
    "结构化",
    "中介",
)
PDF_GENERATE_EXCLUDE = (
    "仅读取",
    "只读",
    "原样",
    "不要生成",
    "read only",
    "vlm",
    "图片分类",
)

PDF_READ_OUTPUT_FIELDS = (
    "plain_text",
    "pages",
    "page_count",
    "char_count",
    "images",
    "image_categories",
    "source",
)
PDF_GENERATE_OUTPUT_FIELDS = (
    "pages",
    "blocks",
    "plain_text",
    "stats",
    "metadata",
)

IMAGE_CATEGORY_DIRS = ("figures", "photos", "diagrams", "icons", "uncategorized")


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def _has_pdf_doc_signal(bl: str) -> bool:
    return any(k in bl for k in PDF_DOC_KEYWORDS)


def _has_word_doc_signal(bl: str) -> bool:
    return any(k in bl for k in ("word", "docx", ".doc", "文档处理"))


def is_pdf_generate(brief: str) -> bool:
    """上传 PDF → 读取原生文字/结构 → JSON 中介 → 写出 PDF。"""
    bl = _brief_lower(brief)
    if not _has_pdf_doc_signal(bl):
        return False
    if _has_word_doc_signal(bl) and ".pdf" not in bl and "pdf" not in bl:
        return False
    if any(k in bl for k in PDF_GENERATE_EXCLUDE) and not any(
        k in bl for k in PDF_GENERATE_ACTION_KEYWORDS
    ):
        return False
    return any(k in bl for k in PDF_GENERATE_ACTION_KEYWORDS)


def is_pdf_full_read(brief: str) -> bool:
    """PDF 只读原生文字；图片走 VLM 并按目录分类存储。"""
    if is_pdf_generate(brief):
        return False
    bl = _brief_lower(brief)
    if not _has_pdf_doc_signal(bl):
        return False
    if _has_word_doc_signal(bl) and ".pdf" not in bl:
        return False
    return any(k in bl for k in PDF_READ_ACTION_KEYWORDS)


def pdf_read_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / PDF 全量读取",
        "goal": (brief or "").strip().splitlines()[0][:200]
        or "上传 PDF，只读原生文字，图片 VLM 描述并分类落盘",
        "input": "用户上传的 .pdf 文件",
        "output": "outputs/document_full.txt + outputs/document_meta.json + outputs/images/<category>/",
        "output_schema": {
            "fields": list(PDF_READ_OUTPUT_FIELDS),
            "text_file": "outputs/document_full.txt",
            "meta_file": "outputs/document_meta.json",
            "images_index": "outputs/images_index.json",
            "images_dir": "outputs/images/",
        },
        "constraints": [
            "正文必须来自 PDF 原生文字层，禁止 LLM 编造正文",
            "图片须导出至分类子目录并由 VLM（可用时）生成 sidecar 描述",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["pdf.native_text", "pdf.image_extract", "vision.vlm"],
        "suggested_handlers": ["direct_python"],
    }


def pdf_generate_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / PDF 生成",
        "goal": (brief or "").strip().splitlines()[0][:200] or "上传 PDF，JSON 中介后生成输出 PDF",
        "input": "用户上传的 .pdf 文件",
        "output": "outputs/document_parsed.json + outputs/generated_document.pdf",
        "output_schema": {
            "fields": list(PDF_GENERATE_OUTPUT_FIELDS),
            "json_file": "outputs/document_parsed.json",
            "pdf_file": "outputs/generated_document.pdf",
        },
        "constraints": [
            "必须真实读取 PDF 并写出 JSON 与 PDF",
            "JSON 为唯一结构化中介；direct_python 负责解析与写 PDF，润色可选用 agent",
        ],
        "suggested_capabilities": ["pdf.parse", "pdf.write", "pdf.polish_optional"],
        "suggested_handlers": ["direct_python", "agent"],
    }


def build_pdf_read_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".pdf"],
        "default_action": "convert",
        "default_output_relpath": "outputs/document_full.txt",
        "default_meta_relpath": "outputs/document_meta.json",
        "default_images_dir": "outputs/images",
        "runtime_kind": "pdf_full_read",
        "output_schema": list(PDF_READ_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Extract native text with PyMuPDF/pypdf; never use LLM for body text.",
            "Export images to outputs/images/{figures,photos,diagrams,icons,uncategorized}/.",
            "When ctx.call_llm supports vision, describe each image to outputs/images/<cat>/<name>.vlm.json.",
            "Write document_full.txt, document_meta.json, images_index.json.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def build_pdf_generate_rule_spec(brief: str) -> Dict[str, Any]:
    bl = _brief_lower(brief)
    wants_polish = any(k in bl for k in ("润色", "改写", "生成正文", "polish", "rewrite"))
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".pdf", ".json", ".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/document_parsed.json",
        "default_pdf_output_relpath": "outputs/generated_document.pdf",
        "runtime_kind": "pdf_generate",
        "optional_llm_polish": wants_polish,
        "output_schema": list(PDF_GENERATE_OUTPUT_FIELDS),
        "requirements": [
            'handlers must include "direct_python"; may include "agent" for optional polish.',
            "Parse PDF into JSON or build from user_query/.txt; write generated_document.pdf from JSON.",
            "Never fabricate content when inputs/ is empty.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def validate_pdf_read_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_pdf_backend(
        pack_dir,
        runtime_kind="pdf_full_read",
        required_tokens=("document_full", "images", ".pdf"),
    )


def validate_pdf_generate_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_pdf_backend(
        pack_dir,
        runtime_kind="pdf_generate",
        required_tokens=("document_parsed", "generated_document"),
    )


def _validate_pdf_backend(
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
    if runtime_kind == "pdf_generate" and handlers and "agent" not in handlers:
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
    if ".pdf" not in py_blob and "fitz" not in py_blob and "pypdf" not in py_blob:
        warnings.append("未发现 PDF 解析相关代码")
    for tok in required_tokens:
        if tok.lower() not in py_blob:
            warnings.append(f"convert 模块可能未覆盖：{tok}")

    return errors, warnings


def minimal_pdf_fixture_bytes() -> bytes:
    try:
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PDF smoke test\nline two", fontsize=12)
        return doc.tobytes()
    except Exception:
        return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def pdf_read_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "PDF 全量读取员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ 中 .pdf，只读原生文字写入 outputs/document_full.txt；"
        "图片导出到 outputs/images/<category>/ 并用 VLM 写 sidecar；元数据写入 document_meta.json。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n"
            "员工必须使用 direct_python：正文仅来自 PDF 原生文字层；图片走 VLM 描述并分类存储。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "只能读 inputs/、写 outputs/；VLM 通过 ctx.call_llm vision 消息。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{merged or clean}\n\nSkill：上传 pdf → 原生文字 + 图片分类 + VLM 描述。",
        "acceptance": [
            "handlers 为 direct_python",
            "document_full.txt 与 PDF 原生文字一致",
            "images_index.json 含分类目录",
        ],
    }


def pdf_generate_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "PDF 生成员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ .pdf → 结构化 JSON（pages/blocks/stats）→ "
        "写入 outputs/document_parsed.json 与 outputs/generated_document.pdf。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n"
            "JSON 为中介；direct_python 解析并写 PDF；润色/改写可走 agent，禁止无输入编造。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "direct_python 读写在先；agent 仅用于可选润色。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{merged or clean}\n\nSkill：上传 → 读取 → JSON 中介 → 写 generated pdf → 可选润色。",
        "acceptance": [
            "输出 document_parsed.json 含 pages/blocks/stats",
            "输出 generated_document.pdf",
            "handlers 含 direct_python，可选 agent",
        ],
    }


def resolve_pdf_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if is_pdf_generate(brief):
        return pdf_generate_orchestration_plan(brief, payload)
    return pdf_read_orchestration_plan(brief, payload)
