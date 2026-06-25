"""PDF 全量读取与 PDF 生成员工：检测、规则、兜底 convert 与包体验证。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
PDF_READ_EXCLUDE = (
    "生成 pdf",
    "写 pdf",
    "写pdf",
    "json 中介生成",
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
    if any(k in bl for k in PDF_READ_EXCLUDE):
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


def render_pdf_read_convert_module() -> str:
    return r"""from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CATEGORY_DIRS = ("figures", "photos", "diagrams", "icons", "uncategorized")


def _classify_image(width: int, height: int, area: int) -> str:
    if width <= 0 or height <= 0:
        return "uncategorized"
    aspect = width / max(height, 1)
    if area < 8000 or max(width, height) < 48:
        return "icons"
    if 0.85 <= aspect <= 1.18 and area >= 40000:
        return "photos"
    if aspect >= 1.35 or aspect <= 0.72:
        return "diagrams"
    return "figures"


def _extract_with_fitz(src_path: Path) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    import fitz  # PyMuPDF

    doc = fitz.open(src_path)
    page_texts: List[str] = []
    pages_meta: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    img_seq = 0
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = (page.get_text("text") or "").strip()
        page_texts.append(text)
        pages_meta.append({"page": page_idx + 1, "char_count": len(text), "has_text": bool(text)})
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                w, h = pix.width, pix.height
                ext = "png"
                data = pix.tobytes(ext)
                category = _classify_image(w, h, w * h)
                img_seq += 1
                images.append({
                    "id": f"p{page_idx + 1}_img{img_seq}",
                    "page": page_idx + 1,
                    "xref": xref,
                    "width": w,
                    "height": h,
                    "category": category,
                    "bytes": data,
                    "ext": ext,
                })
            except Exception:
                continue
    doc.close()
    plain = "\n\n".join(t for t in page_texts if t)
    return plain, pages_meta, images


def _extract_with_pypdf(src_path: Path) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    from pypdf import PdfReader

    reader = PdfReader(str(src_path))
    page_texts: List[str] = []
    pages_meta: List[Dict[str, Any]] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        page_texts.append(text)
        pages_meta.append({"page": idx, "char_count": len(text), "has_text": bool(text)})
    plain = "\n\n".join(t for t in page_texts if t)
    return plain, pages_meta, []


def _write_image_files(images: List[Dict[str, Any]], images_root: Path) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for img in images:
        category = str(img.get("category") or "uncategorized")
        if category not in _CATEGORY_DIRS:
            category = "uncategorized"
        sub = images_root / category
        sub.mkdir(parents=True, exist_ok=True)
        fname = f"{img.get('id') or 'img'}.{img.get('ext') or 'png'}"
        out_path = sub / fname
        out_path.write_bytes(img.get("bytes") or b"")
        catalog.append({
            "id": img.get("id"),
            "page": img.get("page"),
            "category": category,
            "relpath": str(out_path.relative_to(images_root.parent)).replace("\\", "/"),
            "width": img.get("width"),
            "height": img.get("height"),
        })
    return catalog


async def _vlm_describe_image(
    img_path: Path,
    ctx: Dict[str, Any],
    *,
    page: int,
    category: str,
) -> Optional[Dict[str, Any]]:
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        return None
    try:
        raw = img_path.read_bytes()
    except OSError:
        return None
    b64 = base64.b64encode(raw).decode("ascii")
    url = f"data:image/png;base64,{b64}"
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"这是 PDF 第 {page} 页提取的图片（分类：{category}）。"
                        "请用中文简要描述图中文字与关键信息，输出 JSON："
                        '{"description":"","detected_text":"","tags":[]}'
                    ),
                },
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    try:
        res = await asyncio.wait_for(call_llm(messages, max_tokens=600, temperature=0.1), timeout=90.0)
    except Exception:
        return None
    if not isinstance(res, dict) or not res.get("ok"):
        return None
    content = str(res.get("content") or "").strip()
    sidecar = {"description": content[:2000], "vlm_ok": True}
    try:
        if "{" in content:
            parsed = json.loads(content[content.index("{") : content.rindex("}") + 1])
            if isinstance(parsed, dict):
                sidecar = {**sidecar, **parsed}
    except (json.JSONDecodeError, ValueError):
        pass
    return sidecar


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    suffix = src_path.suffix.lower()
    if suffix != ".pdf":
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .pdf")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "document_full.txt"
    if str(rule_spec.get("default_output_relpath") or "").endswith(".txt"):
        txt_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name
    meta_path = output_dir / "document_meta.json"
    if str(rule_spec.get("default_meta_relpath") or "").endswith(".json"):
        meta_path = output_dir / Path(str(rule_spec.get("default_meta_relpath"))).name
    images_root = output_dir / "images"
    if str(rule_spec.get("default_images_dir") or "").strip():
        images_root = output_dir / Path(str(rule_spec.get("default_images_dir"))).name

    warnings: List[str] = []
    try:
        plain, pages_meta, images = _extract_with_fitz(src_path)
        engine = "pymupdf"
    except Exception as exc:
        warnings.append(f"PyMuPDF 解析失败，回退 pypdf：{exc}")
        plain, pages_meta, images = _extract_with_pypdf(src_path)
        engine = "pypdf"

    txt_path.write_text(plain, encoding="utf-8")
    catalog = _write_image_files(images, images_root)

    vlm_results: List[Dict[str, Any]] = []
    for entry in catalog:
        rel = str(entry.get("relpath") or "")
        img_abs = images_root.parent / rel if rel else None
        if not img_abs or not img_abs.is_file():
            continue
        sidecar = await _vlm_describe_image(
            img_abs,
            ctx,
            page=int(entry.get("page") or 0),
            category=str(entry.get("category") or "uncategorized"),
        )
        if sidecar:
            sidecar_path = img_abs.with_suffix(img_abs.suffix + ".vlm.json")
            sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
            entry["vlm_sidecar"] = str(sidecar_path.relative_to(output_dir)).replace("\\", "/")
            vlm_results.append({"id": entry.get("id"), "vlm": True})
        else:
            warnings.append(f"图片 {entry.get('id')} 未获得 VLM 描述（ctx.call_llm 不可用或调用失败）")

    images_index_path = output_dir / "images_index.json"
    images_index = {"images": catalog, "categories": list(_CATEGORY_DIRS), "vlm_count": len(vlm_results)}
    images_index_path.write_text(json.dumps(images_index, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "plain_text": plain,
        "page_count": len(pages_meta),
        "char_count": len(plain),
        "source": src_path.name,
        "engine": engine,
        "pages": pages_meta,
        "image_count": len(catalog),
        "image_categories": {c: sum(1 for i in catalog if i.get("category") == c) for c in _CATEGORY_DIRS},
        "images_index": str(images_index_path.name),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(txt_path),
        "meta_output_path": str(meta_path),
        "images_index_path": str(images_index_path),
        "page_count": len(pages_meta),
        "char_count": len(plain),
        "image_count": len(catalog),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


def render_pdf_generate_convert_module() -> str:
    return r"""from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _blocks_from_text(plain: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for para in plain.split("\n\n"):
        t = para.strip()
        if t:
            blocks.append({"type": "paragraph", "text": t})
    if not blocks and plain.strip():
        blocks.append({"type": "paragraph", "text": plain.strip()})
    return blocks


def _extract_pdf(src_path: Path) -> Dict[str, Any]:
    try:
        import fitz

        doc = fitz.open(src_path)
        pages: List[Dict[str, Any]] = []
        all_text: List[str] = []
        for i in range(len(doc)):
            text = (doc[i].get_text("text") or "").strip()
            all_text.append(text)
            pages.append({"page": i + 1, "text": text, "char_count": len(text)})
        doc.close()
        plain = "\n\n".join(all_text)
        return {"engine": "pymupdf", "pages": pages, "plain_text": plain}
    except Exception:
        from pypdf import PdfReader

        reader = PdfReader(str(src_path))
        pages = []
        all_text = []
        for idx, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            all_text.append(text)
            pages.append({"page": idx, "text": text, "char_count": len(text)})
        return {"engine": "pypdf", "pages": pages, "plain_text": "\n\n".join(all_text)}


def _write_pdf_from_json(payload: Dict[str, Any], out_path: Path) -> None:
    import fitz

    doc = fitz.open()
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    if not pages:
        plain = str(payload.get("plain_text") or "")
        pages = [{"page": 1, "text": plain}]
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        text = str(pg.get("text") or "")
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 72), text[:12000], fontsize=11)
    doc.save(out_path)
    doc.close()


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from modstore_server.office_plaintext_generate import resolve_pdf_document_spec

    suffix = src_path.suffix.lower()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "document_parsed.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    pdf_path = output_dir / "generated_document.pdf"
    if str(rule_spec.get("default_pdf_output_relpath") or "").endswith(".pdf"):
        pdf_path = output_dir / Path(str(rule_spec.get("default_pdf_output_relpath"))).name

    if suffix in (".json", ".txt"):
        spec, _warnings = await resolve_pdf_document_spec(src_path, payload or {}, ctx or {}, rule_spec or {})
        plain = str(spec.get("plain_text") or "")
        pages = spec.get("pages") if isinstance(spec.get("pages"), list) else []
        blocks = _blocks_from_text(plain)
        payload_data: Dict[str, Any] = {
            "metadata": {"source": src_path.name, "format": "pdf", "engine": "plaintext"},
            "pages": pages,
            "blocks": blocks,
            "plain_text": plain,
            "stats": {
                "page_count": len(pages),
                "block_count": len(blocks),
                "char_count": len(plain),
            },
        }
    elif suffix == ".pdf":
        extracted = _extract_pdf(src_path)
        plain = str(extracted.get("plain_text") or "")
        pages = extracted.get("pages") if isinstance(extracted.get("pages"), list) else []
        blocks = _blocks_from_text(plain)
        payload_data = {
            "metadata": {"source": src_path.name, "format": "pdf", "engine": extracted.get("engine")},
            "pages": pages,
            "blocks": blocks,
            "plain_text": plain,
            "stats": {
                "page_count": len(pages),
                "block_count": len(blocks),
                "char_count": len(plain),
            },
        }
    else:
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，支持 .pdf / .json / .txt")

    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_pdf_from_json(payload_data, pdf_path)

    stats = payload_data.get("stats") or {}
    return {
        "output_path": str(json_path),
        "pdf_output_path": str(pdf_path),
        "page_count": stats.get("page_count", 0),
        "block_count": stats.get("block_count", 0),
        "char_count": stats.get("char_count", 0),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
"""


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
        try:
            page = doc.new_page()
            page.insert_text((72, 72), "PDF smoke test\nline two", fontsize=12)
            return doc.tobytes()
        finally:
            doc.close()
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
