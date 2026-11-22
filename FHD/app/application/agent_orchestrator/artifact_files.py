"""Content-verified files belonging to one Agent run; HTTP ownership is checked by callers."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import zipfile
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.application.shipment_excel_elt_security import (
    _open_directory_under_root,
    _open_elt_output_under_root,
    _windows_open_relative,
)
from app.utils.path_io.path_utils import get_app_data_dir

RUN_FILE_MIME_TYPES = {
    ".png": "image/png",
    ".json": "application/json",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_OWNER_BOUND_TYPES = {".pdf", ".docx", ".pptx", ".png", ".json", ".txt"}


def _verify_bound_content(content: bytes, suffix: str) -> None:
    if suffix in {".pdf", ".docx", ".pptx"}:
        _verify_office_content(content, suffix)
    elif suffix == ".png":
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            if image.format != "PNG":
                raise ValueError("browser screenshot format does not match suffix")
            image.verify()
    elif suffix == ".json":
        json.loads(content.decode("utf-8"))
    elif suffix == ".txt":
        content.decode("utf-8")


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
    run = re.fullmatch(r"[A-Za-z0-9_-]{1,160}", run_id)
    artifact = re.fullmatch(r"[A-Za-z0-9_-]{1,160}", artifact_id)
    if run is None or artifact is None:
        raise ValueError("invalid run artifact identity")
    run_id, artifact_id = run.group(0), artifact.group(0)
    root = Path(get_app_data_dir()).resolve() / "agent-artifacts"
    folder = root / run_id
    suffix = "." + artifact_id.partition("_")[0]
    path = folder / (artifact_id + (suffix if suffix in RUN_FILE_MIME_TYPES else ".xlsx"))
    if root.is_symlink() or folder.is_symlink() or path.is_symlink():
        raise ValueError("artifact symlinks are not permitted")
    return path


def _read_artifact(path: Path) -> bytes:
    root = Path(get_app_data_dir()).resolve()
    name = re.fullmatch(r"[A-Za-z0-9_-]{1,160}\.[a-z]{2,4}", path.name)
    if name is None:
        raise ValueError("invalid artifact filename")
    filename = name.group(0)
    parent_fd = _open_directory_under_root(root, path.parent, create=False)
    try:
        if os.name == "nt":
            descriptor = _windows_open_relative(
                parent_fd, filename, directory=False, create=False, for_input=True
            )
        else:
            descriptor = os.open(  # codeql[py/path-injection]
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
            )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("artifact must be a single-link regular file")
            return stream.read()
    finally:
        os.close(parent_fd)


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
    if suffix in _OWNER_BOUND_TYPES:
        if type(owner_user_id) is not int or owner_user_id <= 0 or not tenant_id:
            raise ValueError("office artifact requires account and tenant scope")
        _verify_bound_content(content, suffix)
    artifact_id = f"{suffix[1:]}_{digest[:32]}"
    path = artifact_path(run_id, artifact_id)
    try:
        previous = _read_artifact(path)
    except FileNotFoundError:
        # Reuse the cross-platform pinned-directory writer; a replaced parent
        # or leaf cannot redirect publication between validation and opening.
        with _open_elt_output_under_root(path, Path(get_app_data_dir()).resolve()) as output:
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), 0o600)
            output.write(content)
    else:
        if hashlib.sha256(previous).hexdigest() != digest:
            raise ValueError("existing artifact content differs")
    metadata = {"sha256": digest, "size_bytes": len(content)}
    if suffix in _OWNER_BOUND_TYPES:
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
    content = _read_artifact(path)
    metadata = artifact.get("metadata") or {}
    if len(content) != metadata.get("size_bytes") or hashlib.sha256(
        content
    ).hexdigest() != metadata.get("sha256"):
        raise ValueError("artifact checksum mismatch")
    if path.suffix in _OWNER_BOUND_TYPES:
        if (
            Path(str(artifact.get("name") or "")).suffix.lower() != path.suffix
            or artifact.get("mime_type") != RUN_FILE_MIME_TYPES[path.suffix]
            or metadata.get("run_id") != run_id
        ):
            raise ValueError("office artifact format or run mismatch")
        _verify_bound_content(content, path.suffix)
    return content


read_verified_spreadsheet = read_verified_run_file


def verified_spreadsheet_path(run_id: str, artifact: dict[str, Any]) -> Path:
    read_verified_run_file(run_id, artifact)
    return artifact_path(run_id, artifact["artifact_id"])
