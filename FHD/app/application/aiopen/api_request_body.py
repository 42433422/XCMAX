"""Exact JSON, form and owned-artifact multipart bodies for the API bridge."""

import json
from typing import Any
from urllib.parse import urlencode

from app.application.aiopen.api_artifacts import ApiArtifactError, read_api_export

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_FILES = 16


class ApiBodyError(ValueError):
    pass


def api_request_body(args: dict[str, Any]) -> dict[str, Any]:
    """Construct transport options; never open a model-supplied path or URL."""
    form_request = "form" in args or "files" in args
    if not form_request:
        body = args.get("body", {})
        try:
            json.dumps(body, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ApiBodyError("body 必须是有效 JSON") from exc
        if "body" not in args and str(args.get("method") or "GET").upper() in {"GET", "DELETE"}:
            return {}
        if body is None:
            return {"content": b"null", "headers": {"Content-Type": "application/json"}}
        return {"json": body}
    if "body" in args:
        raise ApiBodyError("body 与 form/files 不能同时提供")
    form = args.get("form", {})
    files = args.get("files", [])
    if not isinstance(form, dict) or not isinstance(files, list) or len(files) > MAX_UPLOAD_FILES:
        raise ApiBodyError("form 必须是字段对象；files 必须是最多 16 项的文件编号列表")
    fields: list[tuple[str, str]] = []
    for key, values in form.items():
        if (
            not isinstance(key, str)
            or not key
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
        ):
            raise ApiBodyError("表单字段名无效")
        values = values if isinstance(values, list) else [values]
        for value in values:
            if not isinstance(value, str):
                raise ApiBodyError("表单值必须是字符串或字符串列表，不自动转换业务字段")
            fields.append((key, value))
    references: list[tuple[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"field", "artifact_id"}:
            raise ApiBodyError("文件只接受 field 与 artifact_id，不接受路径、URL 或文件内容")
        field, artifact_id = entry["field"], entry["artifact_id"]
        if (
            not isinstance(field, str)
            or not field
            or any(ord(char) < 32 or ord(char) == 127 for char in field)
            or not isinstance(artifact_id, str)
        ):
            raise ApiBodyError("文件字段或编号无效")
        references.append((field, artifact_id))
    if not references:
        return {
            "content": urlencode(fields).encode("ascii"),
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        }
    parts: list[tuple[str, Any]] = [(key, (None, value)) for key, value in fields]
    total = 0
    for field, artifact_id in references:
        try:
            content, metadata = read_api_export(artifact_id)
        except ApiArtifactError as exc:
            raise ApiBodyError("附件不存在、已失效或当前账号无权使用") from exc
        total += len(content)
        if total > MAX_UPLOAD_BYTES:
            raise ApiBodyError("附件总大小超过当前 64 MiB 请求限制")
        parts.append((field, (metadata["name"], content, metadata["mime_type"])))
    return {"files": parts}
