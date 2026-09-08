"""Content-verified files belonging to one Agent run; HTTP ownership is checked by callers."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.utils.path_io.path_utils import get_app_data_dir

_COMPONENT = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")


def artifact_path(run_id: str, artifact_id: str) -> Path:
    if not _COMPONENT.fullmatch(run_id) or not _COMPONENT.fullmatch(artifact_id):
        raise ValueError("invalid run artifact identity")
    root = Path(get_app_data_dir()).resolve() / "agent-artifacts"
    folder = root / run_id
    path = folder / f"{artifact_id}.xlsx"
    if root.is_symlink() or folder.is_symlink() or path.is_symlink():
        raise ValueError("artifact symlinks are not permitted")
    return path


def store_spreadsheet(
    run_id: str, content: bytes, *, name: str = "销售报表.xlsx"
) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    artifact_id = f"xlsx_{digest[:32]}"
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
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "uri": f"/api/agent/runs/{run_id}/artifacts/{artifact_id}",
        "metadata": {"sha256": digest, "size_bytes": len(content)},
    }


def verified_spreadsheet_path(run_id: str, artifact: dict[str, Any]) -> Path:
    path = artifact_path(run_id, artifact["artifact_id"])
    content = path.read_bytes()
    metadata = artifact.get("metadata") or {}
    if len(content) != metadata.get("size_bytes") or hashlib.sha256(
        content
    ).hexdigest() != metadata.get("sha256"):
        raise ValueError("artifact checksum mismatch")
    return path
