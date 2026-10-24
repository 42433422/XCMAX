"""Directory admission and batch result aggregation without business write dependencies."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.application import shipment_excel_etl_security as security
from app.application.shipment_etl_profile import ShipmentEtlProfile

from .writing import ResolveProfile


class PreviewFile(Protocol):
    def __call__(
        self,
        file_path: str | Path,
        *,
        include_ledger: bool | str = "auto",
        unit_name_hint: str | None = None,
        workspace_root: str | Path | None = None,
        profile: ShipmentEtlProfile | None = None,
    ) -> dict[str, Any]: ...


class ExecuteFile(Protocol):
    def __call__(
        self,
        file_path: str | Path,
        *,
        include_ledger: bool | str = False,
        unit_name_hint: str | None = None,
        idempotent: bool = True,
        import_products: bool = True,
        import_shipments: bool = True,
        confirm_ledger: bool = False,
        dry_run: bool = False,
        workspace_root: str | Path | None = None,
        profile: ShipmentEtlProfile | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DirectoryFiles:
    root: Path
    paths: list[Path]


def _scan(
    directory: str | Path,
    pattern: str,
    workspace_root: str | Path | None,
) -> DirectoryFiles | dict[str, Any]:
    if not pattern or any(char in pattern for char in ("/", "\\", "\x00")):
        return {
            "success": False,
            "message": "非法文件模式",
            "error_code": "unsafe_pattern",
            "files": [],
        }
    try:
        root = security.resolve_etl_path(directory, workspace_root=workspace_root, must_exist=True)
    except security.ShipmentEtlPathError:
        return {"success": False, "message": "非法目录", "error_code": "unsafe_path", "files": []}
    if not root.is_dir():
        return {"success": False, "message": f"目录不存在: {root}", "files": []}
    # Match only entry names. Letting a caller-supplied glob reach Path.glob would
    # allow directory traversal patterns such as ../*.xlsx.
    return DirectoryFiles(
        root,
        sorted(path for path in root.iterdir() if fnmatch.fnmatchcase(path.name, pattern)),
    )


def preview_directory(
    directory: str | Path,
    *,
    include_ledger: bool | str = "auto",
    pattern: str = "*.xlsx",
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
    resolve_profile: ResolveProfile,
    preview_file: PreviewFile,
) -> dict[str, Any]:
    prof = resolve_profile(profile, profile_id)
    scan = _scan(directory, pattern, workspace_root)
    if not isinstance(scan, DirectoryFiles):
        return scan
    results = []
    total_notes = 0
    for path in scan.paths:
        if path.name.startswith("~$"):
            continue
        result = preview_file(
            path,
            include_ledger=include_ledger,
            unit_name_hint=path.stem,
            workspace_root=workspace_root or scan.root,
            profile=prof,
        )
        note_count = int(result.get("note_count") or 0)
        total_notes += note_count
        results.append(
            {
                "file_path": str(path),
                "file_name": path.name,
                "success": bool(result.get("success")),
                "note_count": note_count,
                "duplicate_note_count": result.get("duplicate_note_count", 0),
                "message": result.get("message"),
                "notes": result.get("notes") or [],
            }
        )
    return {
        "success": True,
        "directory": str(scan.root),
        "file_count": len(results),
        "note_count": total_notes,
        "files": results,
        "profile_id": prof.id,
        "message": f"批量预览完成：{len(results)} 个文件，共 {total_notes} 张单据",
    }


def execute_directory(
    directory: str | Path,
    *,
    include_ledger: bool | str = False,
    pattern: str = "*.xlsx",
    idempotent: bool = True,
    import_products: bool = True,
    import_shipments: bool = True,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
    resolve_profile: ResolveProfile,
    execute_file: ExecuteFile,
) -> dict[str, Any]:
    prof = resolve_profile(profile, profile_id)
    if not dry_run and not security.batch_execute_allowed():
        return {
            "success": False,
            "message": "批量入库默认关闭。需设置环境变量 FHD_SHIPMENT_ETL_ALLOW_BATCH=1",
            "error_code": "batch_disabled",
            "files": [],
        }
    scan = _scan(directory, pattern, workspace_root)
    if not isinstance(scan, DirectoryFiles):
        return scan
    if len(scan.paths) > 50:
        return {
            "success": False,
            "message": f"批量文件过多（{len(scan.paths)}），上限 50，请缩小范围",
            "error_code": "batch_too_large",
            "files": [],
        }
    results = []
    created = skipped = failed = failed_files = 0
    for path in scan.paths:
        if path.name.startswith("~$"):
            continue
        result = execute_file(
            path,
            include_ledger=include_ledger,
            unit_name_hint=path.stem,
            idempotent=idempotent,
            import_products=import_products,
            import_shipments=import_shipments,
            confirm_ledger=confirm_ledger,
            dry_run=dry_run,
            workspace_root=workspace_root or scan.root,
            profile=prof,
        )
        created += int(result.get("shipment_created") or result.get("would_create") or 0)
        skipped += int(result.get("shipment_skipped") or result.get("would_skip") or 0)
        failed += int(result.get("shipment_failed") or 0)
        failed_files += int(not result.get("success"))
        results.append(
            {
                "file_path": str(path),
                "file_name": path.name,
                "success": bool(result.get("success")),
                "shipment_created": result.get("shipment_created", result.get("would_create", 0)),
                "shipment_skipped": result.get("shipment_skipped", result.get("would_skip", 0)),
                "shipment_failed": result.get("shipment_failed", 0),
                "message": result.get("message"),
                "error_code": result.get("error_code"),
            }
        )
    return {
        "success": failed == 0 and failed_files == 0,
        "directory": str(scan.root),
        "file_count": len(results),
        "failed_file_count": failed_files,
        "shipment_created": created,
        "shipment_skipped": skipped,
        "shipment_failed": failed,
        "files": results,
        "closed_loop": not dry_run,
        "dry_run": dry_run,
        "profile_id": prof.id,
        "message": f"{('批量预演' if dry_run else '批量入库')}完成：新建/将建 {created}，跳过 {skipped}，失败 {failed}"
        + (f"，失败文件 {failed_files}" if failed_files else ""),
    }
