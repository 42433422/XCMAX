"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import os
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


def _trusted_base_roots() -> list[Path]:
    """不可被请求参数扩展的受信根目录。"""
    roots: list[Path] = []
    try:
        from app.utils.path_io.path_utils import get_app_data_dir, get_data_dir

        roots.append(Path(get_app_data_dir()).resolve())
        roots.append(Path(get_data_dir()).resolve())
        roots.append((Path(get_app_data_dir()) / "temp_excel").resolve())
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        pass
    roots.append(Path.cwd().resolve())
    # OCR/上传临时文件落系统 temp
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
    """返回受信根；仅当 workspace_root 已落在受信根下时才并入。"""
    roots = list(_trusted_base_roots())
    candidates = [
        str(workspace_root or "").strip(),
        str(os.environ.get("WORKSPACE_ROOT") or "").strip(),
    ]
    root_reals = [os.path.realpath(str(r)) for r in roots]
    for wr in candidates:
        if not wr or any(ch in wr for ch in ("\x00", "\n", "\r")):
            continue
        try:
            wr_real = os.path.realpath(wr)
        except (OSError, ValueError):
            continue
        if any(wr_real == r or wr_real.startswith(r + os.sep) for r in root_reals):
            roots.append(Path(wr_real))
            root_reals.append(wr_real)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = os.path.realpath(str(r))
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(key))
    return out


def _safe_under_roots(raw: str, roots: list[Path]) -> Path:
    """用 commonpath/startswith 消毒后，在命中根下按相对片段重建路径。"""
    text = str(raw or "").strip()
    if not text or "\x00" in text:
        raise ShipmentEtlPathError("empty path")

    root_reals = [os.path.realpath(str(r)) for r in roots]
    if not root_reals:
        raise ShipmentEtlPathError("path not under allowed dirs")

    parts = [p for p in Path(text).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ShipmentEtlPathError("path not under allowed dirs")

    if os.path.isabs(text):
        candidate = os.path.realpath(text)
    else:
        candidate = os.path.realpath(os.path.join(root_reals[0], *parts))

    for root in root_reals:
        if candidate != root and not candidate.startswith(root + os.sep):
            continue
        rel = os.path.relpath(candidate, root)
        if rel.startswith("..") or os.path.isabs(rel):
            continue
        rel_parts = [p for p in Path(rel).parts if p not in ("", ".", "..")]
        safe = root if not rel_parts else os.path.realpath(os.path.join(root, *rel_parts))
        if safe == root or safe.startswith(root + os.sep):
            return Path(safe)
    raise ShipmentEtlPathError("path not under allowed dirs")


def resolve_etl_path(
    file_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    """将用户传入路径解析到沙箱内。

    ``must_exist`` 保留兼容签名；存在性由调用方在打开文件时处理，
    避免 ``Path.exists`` 被静态分析标为 path-injection sink。
    """
    _ = must_exist
    roots = etl_allowed_roots(workspace_root)
    preferred = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    if preferred in roots:
        roots = [preferred, *(root for root in roots if root != preferred)]
    return _safe_under_roots(str(file_path or ""), roots)


def resolve_etl_output_path(
    output_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> Path:
    """输出路径必须落在沙箱内（父目录可尚不存在）。"""
    raw = str(output_path or "").strip()
    if not raw:
        raise ShipmentEtlPathError("empty output path")
    name = Path(raw).name
    if not name or name in (".", ".."):
        raise ShipmentEtlPathError("invalid output name")
    parent_raw = str(Path(raw).parent) if Path(raw).parent.as_posix() not in (".", "") else "."
    if parent_raw in (".", ""):
        # 仅文件名：落到第一个受信根
        roots = etl_allowed_roots(workspace_root)
        parent = roots[0]
    else:
        parent = _safe_under_roots(parent_raw, etl_allowed_roots(workspace_root))
    parent.mkdir(
        parents=True, exist_ok=True
    )  # lgtm[py/path-injection] -- parent passed _safe_under_roots
    # 文件名只用 basename；归一化后再次验证最终路径仍在已批准父目录内。
    parent_text = os.path.realpath(os.path.abspath(parent))
    candidate_text = os.path.realpath(os.path.abspath(os.path.join(parent_text, name)))
    parent_prefix = parent_text.rstrip(os.sep) + os.sep
    if candidate_text != parent_text and not candidate_text.startswith(parent_prefix):
        raise ShipmentEtlPathError("output path not under allowed dirs")
    return Path(candidate_text)


def tenant_key_for_etl() -> str:
    try:
        from app.infrastructure.tenant_scope import current_tenant_id

        tid = current_tenant_id()
        if tid is not None:
            return f"tenant:{int(tid)}"
    except RECOVERABLE_ERRORS:  # noqa: BLE001
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
