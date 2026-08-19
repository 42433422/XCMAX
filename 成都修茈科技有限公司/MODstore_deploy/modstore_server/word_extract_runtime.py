"""Word 全量提取员工：检测、规则、兜底 convert 与包体验证。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modstore_server.word_extract_template import (
    render_word_fallback_convert_module as render_word_fallback_convert_module,
)

WORD_EXTRACT_KEYWORDS = (
    "word",
    "docx",
    ".doc",
    "文档",
    "文本",
    "txt",
)
WORD_EXTRACT_ACTION_KEYWORDS = (
    "提取",
    "解析",
    "保存",
    "转换",
    "全量",
    "格式",
    "信息",
    "extract",
    "parse",
)

WORD_OUTPUT_FIELDS = (
    "metadata",
    "paragraphs",
    "tables",
    "headers_footers",
    "styles",
    "images",
    "comments",
    "core_properties",
    "plain_text",
    "outline",
    "blocks",
    "sections",
)


def is_word_full_extract(brief: str) -> bool:
    from modstore_server.csv_tabular_runtime import is_csv_full_read, is_csv_generate
    from modstore_server.excel_tabular_runtime import is_excel_full_read, is_excel_generate
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate
    from modstore_server.ppt_extract_runtime import is_ppt_full_read, is_ppt_generate
    from modstore_server.txt_extract_runtime import is_txt_full_read, is_txt_generate

    if is_csv_full_read(brief) or is_csv_generate(brief):
        return False
    if is_excel_full_read(brief) or is_excel_generate(brief):
        return False
    if is_txt_full_read(brief) or is_txt_generate(brief):
        return False
    if is_pdf_full_read(brief) or is_pdf_generate(brief):
        return False
    if is_ppt_full_read(brief) or is_ppt_generate(brief):
        return False
    bl = (brief or "").lower()
    has_word_doc = any(k in bl for k in ("word", "docx", ".doc"))
    has_txt_only = (
        any(k in bl for k in (".txt", "txt文件", "txt 文件", "纯文本")) and not has_word_doc
    )
    if has_txt_only:
        return False
    if (
        any(k in bl for k in ("生成", "写入", "write", "generate", "重建", "render"))
        and "提取" not in bl
        and "全量提取" not in bl
    ):
        return False
    has_doc = any(k in bl for k in WORD_EXTRACT_KEYWORDS)
    has_action = any(k in bl for k in WORD_EXTRACT_ACTION_KEYWORDS)
    if not has_doc or not has_action:
        return False
    if not has_word_doc and "txt" in bl:
        return False
    if any(
        k in bl
        for k in (
            "合同",
            "法务",
            "合规",
            "审核",
            "条款",
            "contract",
            "legal",
            "compliance",
            "review",
        )
    ):
        return False
    return True


def word_extract_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / Word 全量提取",
        "goal": (brief or "").strip().splitlines()[0][:200] or "全量提取 Word 文档所有格式与信息",
        "input": "用户上传的 .docx / .doc 文件",
        "output": "document_full.json（结构化全量）+ document_full.txt + images/",
        "output_schema": {
            "fields": list(WORD_OUTPUT_FIELDS),
            "json_file": "outputs/document_full.json",
            "text_file": "outputs/document_full.txt",
            "images_dir": "outputs/images/",
        },
        "constraints": [
            "必须真实解析 docx，禁止 LLM 编造内容",
            "覆盖段落、标题层级、列表、分章节、表格、字体段落样式、图片、页眉页脚、元数据、批注",
            "输出 outline、blocks、sections 与 paragraphs/tables 并存",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": [
            "doc.full_extract",
            "doc.tables",
            "doc.images",
            "doc.metadata",
        ],
        "suggested_handlers": ["direct_python"],
    }


def build_word_extract_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".docx", ".doc"],
        "default_action": "convert",
        "default_output_relpath": "outputs/document_full.json",
        "default_text_output_relpath": "outputs/document_full.txt",
        "default_images_dir": "outputs/images",
        "runtime_kind": "word_full_extract",
        "output_schema": list(WORD_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Extract paragraphs (headings/lists/fonts), tables, outline, blocks, sections, images, styles, headers/footers, core properties, comments.",
            "Write document_full.json and document_full.txt; export images to outputs/images/.",
            "Never claim success unless output files are actually written.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def validate_word_extract_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
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
        errors.append("Word 全量提取员工 handlers 必须包含 direct_python")
    if not has_convert:
        errors.append("backend/vendor 中缺少 convert_file 实现")
    if not any(tok in py_blob for tok in ("docx", "zipfile", "wordprocessingml", "document.xml")):
        warnings.append("未发现 docx/OOXML 解析相关代码")
    rs_path = pack_dir / "rule_spec.json"
    accepted_ext: List[str] = []
    if rs_path.is_file():
        try:
            rs_data = json.loads(rs_path.read_text(encoding="utf-8"))
            if isinstance(rs_data, dict):
                accepted_ext = list(rs_data.get("accepted_extensions") or [])
        except (json.JSONDecodeError, OSError):
            pass
    if ".doc" in accepted_ext or "legacy_doc" in py_blob:
        if "legacy_doc" not in py_blob and "ensure_docx_for_extract" not in py_blob:
            warnings.append("已声明 .doc 但 convert 未集成 legacy_doc.ensure_docx_for_extract")

    for field in (
        "paragraphs",
        "tables",
        "images",
        "core_properties",
        "outline",
        "blocks",
        "sections",
    ):
        if field not in py_blob:
            warnings.append(f"convert 模块可能未覆盖输出字段：{field}")
    for tok in ("heading_level", "list_type", "outline", "numpr", "outlinelvl", "sectpr"):
        if tok not in py_blob:
            warnings.append(f"convert 模块可能未覆盖解析能力：{tok}")

    return errors, warnings


def minimal_docx_bytes() -> bytes:
    """Minimal valid OOXML docx for pipeline smoke tests."""
    import io
    import zipfile

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>smoke</w:t></w:r></w:p></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


def minimal_docx_fixture_b64() -> str:
    import base64

    return base64.b64encode(minimal_docx_bytes()).decode("ascii")


def word_extract_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "Word 全量提取员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python 脚本：读取 inputs/ 中的 .docx，全量提取段落、表格、图片、样式、页眉页脚、元数据、批注；"
        "写入 outputs/document_full.json、outputs/document_full.txt，图片导出到 outputs/images/；"
        "无输入时在 outputs/readme.md 说明期望输入格式。"
    )
    script_runtime = (
        "只能读 inputs/、写 outputs/；允许 python-docx、zipfile、xml.etree；"
        "禁止联网和越界文件访问；必须输出 JSON + TXT + images。"
    )
    workflow_brief = (
        f"{merged or clean}\n\n"
        "Skill 组流程：①接收 Word 上传 ②校验格式 ③全量解析（正文/表格/图片/样式/元数据）"
        "④生成 document_full.json + txt ⑤导出图片 ⑥质量校验 ⑦交付用户。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n"
            "员工必须使用 direct_python 真实解析 docx，输出结构化 JSON（含 paragraphs/tables/images/styles/metadata）"
            "与纯文本摘要，禁止 LLM 编造文档内容。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": script_runtime,
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": workflow_brief,
        "acceptance": [
            "员工包 handlers 为 direct_python 且含 vendor convert 模块",
            "输出 document_full.json 含 paragraphs/tables/images/core_properties",
            "脚本工作流可空跑并生成 outputs/ 说明或样例",
            "Skill 组覆盖上传→解析→校验→交付",
        ],
    }
