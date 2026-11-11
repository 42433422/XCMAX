"""Content-verified files belonging to one Agent run; HTTP ownership is checked by callers."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.utils.path_io.path_utils import get_app_data_dir

RUN_FILE_MIME_TYPES = {
    ".xls": "application/vnd.ms-excel",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _verify_office_content(content: bytes, suffix: str) -> None:
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:
            raise ValueError("invalid PDF artifact content")
        return
    member = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml"}.get(suffix)
    if member is None:
        raise ValueError("unsupported office artifact format")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if member not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                raise ValueError("office artifact format does not match suffix")
            if archive.getinfo("[Content_Types].xml").file_size > 1_048_576:
                raise ValueError("office content type manifest too large")
            expected = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                if suffix == ".docx"
                else "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
            )
            types = fromstring(archive.read("[Content_Types].xml"))
            if not any(
                row.tag.rsplit("}", 1)[-1] == "Override"
                and row.get("PartName") == "/" + member
                and row.get("ContentType") == expected
                for row in types
            ):
                raise ValueError("office content type does not match suffix")
    except (zipfile.BadZipFile, ParseError, DefusedXmlException) as exc:
        raise ValueError("invalid office artifact content") from exc


def artifact_path(run_id: str, artifact_id: str) -> Path:
    # 内联字面量正则（与 label_job_service 同款）：CodeQL 将 fullmatch 校验识别为
    # 路径注入屏障；预编译对象不被识别，会导致 py/path-injection 误报。
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", run_id):
        raise ValueError("invalid run artifact identity")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", artifact_id):
        raise ValueError("invalid run artifact identity")
    root = Path(get_app_data_dir()).resolve() / "agent-artifacts"
    folder = root / run_id
    suffix = "." + artifact_id.partition("_")[0]
    path = folder / (artifact_id + (suffix if suffix in RUN_FILE_MIME_TYPES else ".xlsx"))
    if root.is_symlink() or folder.is_symlink() or path.is_symlink():
        raise ValueError("artifact symlinks are not permitted")
    return path


def store_run_file(
    run_id: str,
    content: bytes,
    *,
    name: str = "销售报表.xlsx",
    owner_user_id: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(name).suffix.lower()
    if suffix not in RUN_FILE_MIME_TYPES:
        raise ValueError("unsupported run file format")
    if suffix in {".pdf", ".docx", ".pptx"}:
        if type(owner_user_id) is not int or owner_user_id <= 0 or not tenant_id:
            raise ValueError("office artifact requires account and tenant scope")
        _verify_office_content(content, suffix)
    artifact_id = f"{suffix[1:]}_{digest[:32]}"
    path = artifact_path(run_id, artifact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".artifact-", delete=False)
    temporary = Path(output.name)
    try:
        with output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("existing artifact content differs") from None
    finally:
        temporary.unlink(missing_ok=True)
    metadata = {"sha256": digest, "size_bytes": len(content)}
    if suffix in {".pdf", ".docx", ".pptx"}:
        metadata.update(run_id=run_id, owner_user_id=str(owner_user_id), tenant_id=str(tenant_id))
    return {
        "artifact_id": artifact_id,
        "artifact_type": "file",
        "name": Path(name).name,
        "mime_type": RUN_FILE_MIME_TYPES[suffix],
        "uri": f"/api/agent/runs/{run_id}/artifacts/{artifact_id}",
        "metadata": metadata,
    }


store_spreadsheet = store_run_file


def read_verified_run_file(run_id: str, artifact: dict[str, Any]) -> bytes:
    path = artifact_path(run_id, artifact["artifact_id"])
    content = path.read_bytes()
    metadata = artifact.get("metadata") or {}
    if len(content) != metadata.get("size_bytes") or hashlib.sha256(
        content
    ).hexdigest() != metadata.get("sha256"):
        raise ValueError("artifact checksum mismatch")
    if path.suffix in {".pdf", ".docx", ".pptx"}:
        if (
            Path(str(artifact.get("name") or "")).suffix.lower() != path.suffix
            or artifact.get("mime_type") != RUN_FILE_MIME_TYPES[path.suffix]
            or metadata.get("run_id") != run_id
        ):
            raise ValueError("office artifact format or run mismatch")
        _verify_office_content(content, path.suffix)
    return content


read_verified_spreadsheet = read_verified_run_file


def verified_spreadsheet_path(run_id: str, artifact: dict[str, Any]) -> Path:
    read_verified_run_file(run_id, artifact)
    return artifact_path(run_id, artifact["artifact_id"])
