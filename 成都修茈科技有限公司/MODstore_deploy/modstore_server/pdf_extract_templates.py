"""Generated direct-Python converter source templates for PDF employee packs."""

from __future__ import annotations


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
