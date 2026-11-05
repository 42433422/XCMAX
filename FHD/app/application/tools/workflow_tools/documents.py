"""Office generation and the downloadable artifact response."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from app.application.tools.workflow_tools.contracts import Payload


def generate_office_document(
    args: Payload,
    generate: Callable[[str, Literal["docx", "xlsx"]], tuple[bytes, str]],
    store: Callable[[bytes, str, str], str],
) -> Payload:
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
    mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if output_format == "xlsx"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    token = store(content, name, mime)
    url = f"/api/ai/kitten/document/pickup/{token}"
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
                "summary": request[:500],
                "preview": {
                    "file_name": name,
                    "download_url": url,
                    "output_format": output_format,
                },
                "metadata": {"pickup_token": token, "generator": "generate_office_document"},
            }
        ],
        "assistant_hint": "将 download_url 原样写入回复（可做成 Markdown 链接）；不要再次调用 generate_office_document，除非用户明确要求重新生成。",
    }
