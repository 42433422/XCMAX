"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import os
from pathlib import Path

from app.utils.safe_download_path import UnsafeDownloadPathError, resolve_under_allowed_dirs


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


def etl_allowed_roots(workspace_root: str | Path | None = None) -> list[Path]:
    roots: list[Path] = []
    try:
        from app.utils.path_utils import get_app_data_dir, get_data_dir

        roots.append(Path(get_app_data_dir()).resolve())
        roots.append(Path(get_data_dir()).resolve())
        roots.append((Path(get_app_data_dir()) / "temp_excel").resolve())
    except Exception:  # noqa: BLE001
        pass

    wr = str(workspace_root or "").strip() or str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    if wr:
        roots.append(Path(wr).expanduser().resolve())
    cwd = Path.cwd().resolve()
    roots.append(cwd)
    # 单测临时目录（仅 pytest 会话）
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FHD_SHIPMENT_ETL_ALLOW_TMP"):
        import tempfile

        roots.append(Path(tempfile.gettempdir()).resolve())
    # 去重保序
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def resolve_etl_path(
    file_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    """将用户传入路径解析到沙箱内；相对路径优先相对 workspace_root。"""
    raw = str(file_path or "").strip()
    if not raw:
        raise ShipmentEtlPathError("empty path")
    wr = str(workspace_root or "").strip() or str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        base = Path(wr).expanduser().resolve() if wr else Path.cwd().resolve()
        candidate = (base / raw).resolve()
    try:
        resolved = resolve_under_allowed_dirs(str(candidate), etl_allowed_roots(wr or None))
    except UnsafeDownloadPathError as exc:
        raise ShipmentEtlPathError(str(exc)) from exc
    if must_exist and not resolved.is_file() and not resolved.is_dir():
        raise ShipmentEtlPathError(f"path not found: {resolved}")
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
    wr = str(workspace_root or "").strip() or str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        base = Path(wr).expanduser().resolve() if wr else Path.cwd().resolve()
        candidate = (base / raw).resolve()
    parent = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        resolve_under_allowed_dirs(str(parent), etl_allowed_roots(wr or None))
    except UnsafeDownloadPathError as exc:
        raise ShipmentEtlPathError(str(exc)) from exc
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
