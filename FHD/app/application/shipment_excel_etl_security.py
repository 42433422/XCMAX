"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import os
from pathlib import Path

from app.utils.safe_download_path import (
    UnsafeDownloadPathError,
    is_path_within,
    resolve_under_allowed_dirs,
)


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


def _trusted_base_roots() -> list[Path]:
    """不可被请求参数扩展的受信根目录。"""
    roots: list[Path] = []
    try:
        from app.utils.path_utils import get_app_data_dir, get_data_dir

        roots.append(Path(get_app_data_dir()).resolve())
        roots.append(Path(get_data_dir()).resolve())
        roots.append((Path(get_app_data_dir()) / "temp_excel").resolve())
    except Exception:  # noqa: BLE001
        pass
    roots.append(Path.cwd().resolve())
    # OCR/上传临时文件落系统 temp；仍须经 resolve_under_allowed_dirs 校验
    import tempfile

    roots.append(Path(tempfile.gettempdir()).resolve())
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def etl_allowed_roots(workspace_root: str | Path | None = None) -> list[Path]:
    roots = list(_trusted_base_roots())
    wr = str(workspace_root or "").strip() or str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    if wr:
        wr_path = Path(wr).expanduser().resolve()
        # workspace_root 只能是受信根之下的子目录，禁止把任意用户路径抬升为根
        if any(is_path_within(base, wr_path) for base in roots):
            roots.append(wr_path)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _resolve_candidate(
    raw: str,
    *,
    workspace_root: str | Path | None,
) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    roots = etl_allowed_roots(workspace_root)
    wr = str(workspace_root or "").strip() or str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    if wr:
        wr_path = Path(wr).expanduser().resolve()
        if any(is_path_within(base, wr_path) for base in roots):
            return (wr_path / raw).resolve()
    return (roots[0] / raw).resolve()


def resolve_etl_path(
    file_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    """将用户传入路径解析到沙箱内；相对路径优先相对受信 workspace_root。"""
    raw = str(file_path or "").strip()
    if not raw:
        raise ShipmentEtlPathError("empty path")
    candidate = _resolve_candidate(raw, workspace_root=workspace_root)
    try:
        resolved = resolve_under_allowed_dirs(str(candidate), etl_allowed_roots(workspace_root))
    except UnsafeDownloadPathError as exc:
        raise ShipmentEtlPathError("path not under allowed dirs") from exc
    if must_exist and not resolved.is_file() and not resolved.is_dir():
        raise ShipmentEtlPathError("path not found")
    return resolved


def resolve_etl_output_path(
    output_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> Path:
    """输出路径必须落在沙箱内（父目录可尚不存在）。"""
    raw = str(output_path or "").strip()
    if not raw:
        raise ShipmentEtlPathError("empty output path")
    candidate = _resolve_candidate(raw, workspace_root=workspace_root)
    parent = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        resolve_under_allowed_dirs(str(parent), etl_allowed_roots(workspace_root))
    except UnsafeDownloadPathError as exc:
        raise ShipmentEtlPathError("path not under allowed dirs") from exc
    return candidate


def tenant_key_for_etl() -> str:
    try:
        from app.infrastructure.tenant_scope import current_tenant_id

        tid = current_tenant_id()
        if tid is not None:
            return f"tenant:{int(tid)}"
    except Exception:  # noqa: BLE001
        pass
    return "tenant:local"


def batch_execute_allowed() -> bool:
    return os.environ.get("FHD_SHIPMENT_ETL_ALLOW_BATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def direct_execute_allowed() -> bool:
    """无预览直写生产库：默认关闭，需显式环境开关。"""
    for key in ("FHD_EXCEL_ETL_ALLOW_DIRECT", "FHD_SHIPMENT_ETL_ALLOW_DIRECT"):
        if os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False
