"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import os
from pathlib import Path


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


class ShipmentEtlRuntimeDataDirError(ShipmentEtlPathError):
    """The desktop user-data root is unavailable; never substitute cwd."""

    code = "ETL_RUNTIME_DATA_DIR_UNAVAILABLE"
    status_code = 503

    def __init__(self, message: str = "ETL 运行数据目录不可用，已拒绝使用应用安装目录") -> None:
        super().__init__(message)


def _etl_app_data_root() -> Path:
    """Resolve the only persistent root permitted for legacy ETL state.

    In packaged desktop mode the process cwd is the bundled backend directory.
    A relative ``XCAGI_DATA_DIR`` is therefore unsafe as well: reject it before
    ``get_app_data_dir`` can resolve it against the application bundle.
    """

    explicit = os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR")
    if explicit and not Path(explicit).expanduser().is_absolute():
        raise ShipmentEtlRuntimeDataDirError()
    try:
        from app.utils.path_utils import get_app_data_dir

        root = Path(get_app_data_dir()).expanduser()
        if not root.is_absolute():
            raise ShipmentEtlRuntimeDataDirError()
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    except ShipmentEtlRuntimeDataDirError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert environment failure to stable ETL code
        raise ShipmentEtlRuntimeDataDirError() from exc


def etl_runtime_data_dir() -> Path:
    """Return legacy ETL's persistent data directory under app user-data."""

    try:
        root = _etl_app_data_root() / "data"
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()
    except ShipmentEtlRuntimeDataDirError:
        raise
    except OSError as exc:
        raise ShipmentEtlRuntimeDataDirError() from exc


def etl_runtime_output_dir() -> Path:
    """Return the dedicated runtime export root for bare ETL output names."""

    try:
        root = etl_runtime_data_dir() / "etl" / "outputs"
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()
    except ShipmentEtlRuntimeDataDirError:
        raise
    except OSError as exc:
        raise ShipmentEtlRuntimeDataDirError() from exc


def _trusted_base_roots() -> list[Path]:
    """不可被请求参数扩展的受信根目录。"""
    app_data_root = _etl_app_data_root()
    roots: list[Path] = [
        app_data_root,
        etl_runtime_data_dir(),
        (app_data_root / "temp_excel").resolve(),
    ]
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
    return _safe_under_roots(str(file_path or ""), etl_allowed_roots(workspace_root))


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
        # Bare output names must not inherit the packaged process cwd.
        parent = etl_runtime_output_dir()
    else:
        parent = _safe_under_roots(parent_raw, etl_allowed_roots(workspace_root))
    parent.mkdir(parents=True, exist_ok=True)
    # 文件名只用 basename，切断用户路径 taint
    return parent / name


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
