"""Office generation and the downloadable artifact response."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from app.application.tools.workflow_tools.contracts import Payload


def _fill_from_template(args: Payload, runtime_context: Payload | None) -> Payload | None:
    template_id = str(args.get("template_id") or "").strip()
    template_name = str(args.get("template_name") or args.get("template") or "").strip()
    if not template_id and not template_name:
        return None
    from app.domain.shared_services.kitten_ai_document.template_fill import (
        fill_document_from_template,
    )

    tenant_raw = (runtime_context or {}).get("tenant_id")
    try:
        filled = fill_document_from_template(
            template_id=template_id or None,
            template_name=template_name or None,
            rows=args.get("rows") if isinstance(args.get("rows"), list) else None,
            file_path=str(args.get("file_path") or args.get("source_file") or "").strip() or None,
            sheet_name=str(args.get("sheet_name") or "").strip() or None,
            field_mapping=args.get("field_mapping")
            if isinstance(args.get("field_mapping"), dict)
            else None,
            output_name=str(args.get("output_name") or "").strip() or None,
            tenant_id=int(tenant_raw) if str(tenant_raw or "").isdigit() else None,
            workspace_root=str((runtime_context or {}).get("workspace_root") or "") or None,
            runtime_context=runtime_context,
        )
    except ValueError as error:
        return {"success": False, "error": "template_fill_failed", "message": str(error)}
    return {
        "success": True,
        "message": f"已按模板《{filled['template_name']}》写入 {filled['row_count']} 行真实数据。",
        "file_name": filled["file_name"],
        "content": filled["content"],
        "template": {
            "template_id": filled.get("template_id"),
            "template_name": filled.get("template_name"),
            "row_count": filled.get("row_count"),
            "field_mapping": filled.get("field_mapping"),
            "unmapped_labels": filled.get("unmapped_labels"),
        },
    }


def generate_office_document(
    args: Payload,
    generate: Callable[[str, Literal["docx", "xlsx"]], tuple[bytes, str]],
    store: Callable[[bytes, str, str], str],
    *,
    runtime_context: Payload | None = None,
) -> Payload:
    template_result = _fill_from_template(args, runtime_context)
    if template_result is not None:
        if not template_result.get("success"):
            return template_result
        content = template_result.pop("content")
        return _store_result(
            content,
            str(template_result["file_name"]),
            "xlsx",
            str(args.get("user_request") or "").strip(),
            store,
            {"generator": "generate_office_document:template_fill", **template_result["template"]},
        )

    request = str(
        args.get("user_request")
        or args.get("prompt")
        or args.get("request")
        or args.get("message")
        or ""
    ).strip()
    raw_format = str(args.get("output_format") or "docx").lower().strip()
    output_format: Literal["docx", "xlsx"] = "xlsx" if raw_format == "xlsx" else "docx"
    if not request:
        return {"success": False, "error": "missing_user_request"}
    content, name = generate(request, output_format)
    return _store_result(content, name, output_format, request, store)


def _store_result(
    content: bytes,
    name: str,
    output_format: str,
    summary: str,
    store: Callable[[bytes, str, str], str],
    metadata_extra: Payload | None = None,
) -> Payload:
    mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if output_format == "xlsx"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    token = store(content, name, mime)
    url = f"/api/ai/kitten/document/pickup/{token}"
    metadata = {"pickup_token": token, "generator": "generate_office_document"}
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "success": True,
        "message": f"已生成《{name}》。请让用户在浏览器打开以下路径下载（一次性有效，勿泄露 token）：",
        "pickup_token": token,
        "file_name": name,
        "download_url": url,
        "artifacts": [
            {
                "artifact_type": "office_document",
                "name": name,
                "source": "generate_office_document",
                "uri": url,
                "mime_type": mime,
                "summary": summary[:500],
                "preview": {
                    "file_name": name,
                    "download_url": url,
                    "output_format": output_format,
                },
                "metadata": metadata,
            }
        ],
        "assistant_hint": "将 download_url 原样写入回复（可做成 Markdown 链接）；不要再次调用 generate_office_document，除非用户明确要求重新生成。",
    }
