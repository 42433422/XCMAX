from __future__ import annotations

import json
from io import BytesIO
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


def _extract_with_pypdf(src_path: Path) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    reader = PdfReader(str(src_path))
    page_texts: List[str] = []
    pages_meta: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    img_seq = 0
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        page_texts.append(text)
        pages_meta.append({"page": idx, "char_count": len(text), "has_text": bool(text)})
        try:
            page_images = list(page.images)
        except (AttributeError, KeyError, OSError, PdfReadError, TypeError, ValueError):
            page_images = []
        for image_file in page_images:
            try:
                pil_image = image_file.image
                if pil_image.mode not in {"RGB", "RGBA"}:
                    pil_image = pil_image.convert("RGB")
                output = BytesIO()
                pil_image.save(output, format="PNG")
                width, height = pil_image.size
                img_seq += 1
                images.append(
                    {
                        "id": f"p{idx}_img{img_seq}",
                        "page": idx,
                        "width": width,
                        "height": height,
                        "category": _classify_image(width, height, width * height),
                        "bytes": output.getvalue(),
                        "ext": "png",
                    }
                )
            except (AttributeError, KeyError, OSError, TypeError, ValueError):
                continue
    plain = "\n\n".join(t for t in page_texts if t)
    return plain, pages_meta, images


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
        catalog.append(
            {
                "id": img.get("id"),
                "page": img.get("page"),
                "category": category,
                "relpath": str(out_path.relative_to(images_root.parent)).replace("\\", "/"),
                "width": img.get("width"),
                "height": img.get("height"),
            }
        )
    return catalog


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

    from app.mod_sdk.host_services import read_native_document

    document_facts = read_native_document(src_path)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "document_full.txt"
    if str(rule_spec.get("default_output_relpath") or "").endswith(".txt"):
        txt_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name
    meta_path = output_dir / "document_meta.json"
    if str(rule_spec.get("default_meta_relpath") or "").endswith(".json"):
        meta_path = output_dir / Path(str(rule_spec.get("default_meta_relpath"))).name
    if output_path.suffix.lower() == ".txt":
        txt_path = output_path
    elif output_path.suffix.lower() == ".json":
        meta_path = output_path
    images_root = output_dir / "images"
    if str(rule_spec.get("default_images_dir") or "").strip():
        images_root = output_dir / Path(str(rule_spec.get("default_images_dir"))).name

    warnings: List[str] = []
    plain, pages_meta, images = _extract_with_pypdf(src_path)
    engine = "pypdf"

    txt_path.write_text(plain, encoding="utf-8")
    catalog = _write_image_files(images, images_root)

    # A model transport or a readable file is not permission to send its content.
    # This local reader has no verified per-document egress grant, so preserve
    # the original images without invoking an implicit model enrichment.
    image_semantics = {
        "status": "blocked" if catalog else "not_applicable",
        "reason": "model_content_egress_not_authorized" if catalog else "no_embedded_images",
    }
    status = document_facts["status"]
    if catalog:
        if status == "complete":
            status = "partial"
        warnings.append("未取得文档内容外发授权，未生成图片语义描述；原始图片已保留。")

    images_index_path = output_dir / "images_index.json"
    images_index = {
        "images": catalog,
        "categories": list(_CATEGORY_DIRS),
        "vlm_count": 0,
        "image_semantics": image_semantics,
    }
    images_index_path.write_text(
        json.dumps(images_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    meta = {
        "status": status,
        "image_semantics": image_semantics,
        "plain_text": plain,
        "page_count": len(pages_meta),
        "char_count": len(plain),
        "source": src_path.name,
        "engine": engine,
        "pages": pages_meta,
        "image_count": len(catalog),
        "image_categories": {
            c: sum(1 for i in catalog if i.get("category") == c) for c in _CATEGORY_DIRS
        },
        "images_index": str(images_index_path.name),
    }
    meta["document_facts"] = document_facts
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if output_path.suffix.lower() == ".json" and output_path != meta_path:
        output_path.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")

    return {
        "status": status,
        "image_semantics": image_semantics,
        "output_path": str(txt_path),
        "meta_output_path": str(meta_path),
        "images_index_path": str(images_index_path),
        "page_count": len(pages_meta),
        "char_count": len(plain),
        "plain_text": plain,
        "image_count": len(catalog),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
