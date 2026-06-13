"""Excel path resolution for workflow tools (split from workflow.py)."""

from __future__ import annotations

from pathlib import Path


def resolve_safe_excel_path(workspace_root_or_file: str, file_path: str | None = None) -> Path:
    """解析安全的 Excel 文件路径，支持多路径查找。"""
    if file_path is None:
        base = Path.cwd().resolve()
        fp = workspace_root_or_file
    else:
        base = Path(workspace_root_or_file).resolve()
        fp = file_path

    if Path(fp).is_absolute():
        p = Path(fp).resolve()
        if p.exists():
            return p
    else:
        p = (base / fp).resolve()
        if p.exists():
            try:
                p.relative_to(base)
                return p
            except ValueError:
                pass

    search_paths = []
    upload_dirs = []

    if base.name == "XCAGI":
        upload_dirs.append(base.parent / "uploads")
        upload_dirs.append(base.parent / "424")
        upload_dirs.append(base / "uploads")

    cwd = Path.cwd().resolve()
    upload_dirs.extend(
        [
            cwd / "uploads",
            cwd.parent / "uploads",
            cwd.parent / "424",
            cwd / "424",
            Path("E:/FHD/uploads"),
            Path("E:/FHD/424"),
            Path("E:/FHD/XCAGI/uploads"),
        ]
    )

    seen = set()
    for d in upload_dirs:
        if d.exists() and str(d.resolve()) not in seen:
            seen.add(str(d.resolve()))
            search_paths.append(d)

    fp_name = Path(fp).name
    for search_dir in search_paths:
        candidate = search_dir / fp_name
        if candidate.exists():
            return candidate.resolve()

    if Path(fp).is_absolute():
        return Path(fp).resolve()
    return (base / fp).resolve()
