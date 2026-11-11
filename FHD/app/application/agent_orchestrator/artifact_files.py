"""Content-verified files belonging to one Agent run; HTTP ownership is checked by callers."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.utils.path_io.path_utils import get_app_data_dir

RUN_FILE_MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


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


def store_run_file(run_id: str, content: bytes, *, name: str = "销售报表.xlsx") -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(name).suffix.lower()
    suffix = suffix if suffix in RUN_FILE_MIME_TYPES else ".xlsx"
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
    return {
        "artifact_id": artifact_id,
        "artifact_type": "file",
        "name": Path(name).name,
        "mime_type": RUN_FILE_MIME_TYPES[suffix],
        "uri": f"/api/agent/runs/{run_id}/artifacts/{artifact_id}",
        "metadata": {"sha256": digest, "size_bytes": len(content)},
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
    return content


read_verified_spreadsheet = read_verified_run_file


def verified_spreadsheet_path(run_id: str, artifact: dict[str, Any]) -> Path:
    read_verified_run_file(run_id, artifact)
    return artifact_path(run_id, artifact["artifact_id"])
