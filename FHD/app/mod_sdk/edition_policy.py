"""宿主发行版（edition）策略：generic / minimal / full。"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS, MINIMAL_HOST_MOD_IDS
from app.mod_sdk.product_skus import (
    bundled_mod_ids_for_sku,
    configure_sku_edition_env,
    resolve_product_sku,
)

logger = logging.getLogger(__name__)

Edition = Literal["minimal", "generic", "full"]


def _dedupe_mod_ids(mod_ids: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for mod_id in mod_ids:
        mid = str(mod_id or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return tuple(out)


def resolve_edition() -> Edition:
    """与 ``platform_shell._resolve_edition`` 一致，供路由与中间件共用。"""
    explicit = (os.environ.get("XCAGI_EDITION") or "").strip().lower()
    if explicit in ("minimal", "generic", "full"):
        return cast("Edition", explicit)
    minimal = (os.environ.get("XCAGI_MINIMAL_EDITION") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    generic = (os.environ.get("XCAGI_GENERIC_EDITION") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if minimal:
        return "minimal"
    if generic:
        return "generic"
    return "full"


def should_register_host_legacy_routes() -> bool:
    """非 full 发行版默认不挂载 legacy_gaps 大批兼容路由。"""
    flag = (os.environ.get("XCAGI_REGISTER_LEGACY_ROUTES") or "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    from app.mod_sdk.host_profile import edition_legacy_routes_enabled

    return edition_legacy_routes_enabled(resolve_edition())


def edition_mod_ids(edition: Edition | None = None) -> tuple[str, ...]:
    sku_mods = bundled_mod_ids_for_sku()
    if sku_mods:
        return sku_mods
    ed = edition or resolve_edition()
    if ed == "minimal":
        return MINIMAL_HOST_MOD_IDS
    if ed == "generic":
        return GENERIC_HOST_MOD_IDS
    return _dedupe_mod_ids((*MINIMAL_HOST_MOD_IDS, *GENERIC_HOST_MOD_IDS))


def configure_edition_defaults(*, desktop: bool = False) -> Edition:
    """填充进程环境默认：打包桌面与显式 ``XCAGI_DEFAULT_EDITION`` 时偏向 generic 壳。"""
    if resolve_product_sku():
        configure_sku_edition_env()
    ed = resolve_edition()
    if ed != "full":
        return ed
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION"):
        return ed
    default_ed = (os.environ.get("XCAGI_DEFAULT_EDITION") or "").strip().lower()
    is_desktop = desktop or (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if is_desktop or default_ed == "generic":
        os.environ.setdefault("XCAGI_GENERIC_EDITION", "1")
        os.environ.setdefault("XCAGI_PLATFORM_SHELL", "1")
    elif default_ed == "minimal":
        os.environ.setdefault("XCAGI_MINIMAL_EDITION", "1")
        os.environ.setdefault("XCAGI_PLATFORM_SHELL", "1")
    return resolve_edition()


def _extra_mod_seed_roots() -> list[Path]:
    """除主 mods 根外，开发树中常见的 bridge 种子目录（如 FHD/mods 缺件时回退 XCAGI/mods）。"""
    roots: list[Path] = []
    for raw in (
        os.environ.get("XCAGI_EXTRA_SEED_MODS_DIR"),
        os.environ.get("XCAGI_REPO_MODS_DIR"),
    ):
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                roots.append(p)
    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in ("XCAGI/mods", "FHD/XCAGI/mods"):
            p = (parent / rel).resolve()
            if p.is_dir() and p not in roots:
                roots.append(p)
    return roots


def _resolve_mod_seed_source(mod_id: str, primary: Path) -> Path | None:
    trial = primary / mod_id
    if trial.is_dir():
        return trial
    for root in _extra_mod_seed_roots():
        alt = root / mod_id
        if alt.is_dir():
            return alt
    return None


_BUNDLED_MOD_IGNORES = ("__pycache__", "*.py[co]", ".DS_Store")
_RETIRED_BUNDLED_MOD_IDS = ("xcagi-wechat-bridge",)


def _bundled_mod_digest(root: Path) -> str:
    """Return a stable digest for bundled Mod source files, excluding runtime caches."""
    digest = sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.name == ".DS_Store":
            continue
        if path.is_dir() or path.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _archive_bundled_mod(dst: Path, root: Path) -> Path:
    replaced_digest = _bundled_mod_digest(dst) if dst.is_dir() else "non-directory"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive = (
        root.parent / "bundled-mod-backups" / dst.name / (f"{timestamp}-{replaced_digest[:12]}")
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(dst, archive)
    return archive


def _refresh_bundled_mod(src: Path, dst: Path, root: Path) -> tuple[str, str]:
    """Seed or atomically refresh one official Mod, archiving replaced contents."""
    source_digest = _bundled_mod_digest(src)
    if dst.is_dir() and _bundled_mod_digest(dst) == source_digest:
        return ("skipped", "already current")

    stage = root / f".xcagi-seed-{dst.name}-{uuid4().hex}"
    archive: Path | None = None
    try:
        shutil.copytree(src, stage, ignore=shutil.ignore_patterns(*_BUNDLED_MOD_IGNORES))
        if dst.exists():
            archive = _archive_bundled_mod(dst, root)
        try:
            os.replace(stage, dst)
        except OSError:
            if archive is not None and archive.exists() and not dst.exists():
                os.replace(archive, dst)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)

    if archive is None:
        return ("seeded", str(dst))
    return ("refreshed", f"archived previous copy: {archive}")


def _archive_retired_bundled_mods(root: Path) -> list[dict[str, str]]:
    """Remove retired official code from the active scan root without deleting it."""
    results: list[dict[str, str]] = []
    for mod_id in _RETIRED_BUNDLED_MOD_IDS:
        dst = root / mod_id
        if not dst.exists():
            continue
        try:
            archive = _archive_bundled_mod(dst, root)
            results.append(
                {
                    "mod_id": mod_id,
                    "status": "retired",
                    "message": f"archived retired copy: {archive}",
                }
            )
        except OSError:
            results.append(
                {"mod_id": mod_id, "status": "error", "message": "retired mod archive failed"}
            )
    return results


def _seed_bundled_employee_packs(bundle: Path, root: Path) -> list[dict[str, str]]:
    """Seed missing official employee packs from the read-only desktop bundle."""
    source_root = bundle / "_employees"
    if not source_root.is_dir():
        return []

    destination_root = root / "_employees"
    destination_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, str]] = []
    for source in sorted(source_root.iterdir(), key=lambda path: path.name):
        if not source.is_dir() or not (source / "manifest.json").is_file():
            continue
        pack_id = source.name
        result_id = f"_employees/{pack_id}"
        destination = destination_root / pack_id
        if destination.is_dir():
            results.append({"mod_id": result_id, "status": "skipped", "message": "already present"})
            continue
        try:
            shutil.copytree(source, destination)
            results.append({"mod_id": result_id, "status": "seeded", "message": str(destination)})
        except OSError:
            results.append(
                {"mod_id": result_id, "status": "error", "message": "employee pack seed failed"}
            )
    return results


def bundled_mods_dir() -> Path | None:
    """PyInstaller 或源码树中的只读 Mod 种子目录。"""
    for raw in (
        os.environ.get("XCAGI_BUNDLED_MODS_DIR"),
        os.environ.get("XCAGI_SEED_MODS_DIR"),
    ):
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    import sys

    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ""))
        for name in ("mods", "XCAGI/mods"):
            p = base / name
            if p.is_dir():
                return p
    cwd = Path.cwd()
    for rel in ("mods", "XCAGI/mods", "FHD/mods"):
        p = (cwd / rel).resolve()
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        trial = parent / "mods"
        if trial.is_dir() and (trial / "xcagi-planner-bridge").is_dir():
            return trial
    return None


def seed_edition_mods_from_bundle(
    edition: Edition | None = None,
    *,
    mods_root: str | Path | None = None,
) -> list[dict[str, str]]:
    """Materialize the exact official bridge Mods shipped with this desktop build.

    Existing official Mods are content-compared with the read-only bundle. A
    stale copy is archived outside the active Mods directory and atomically
    replaced. Customer-installed Mods and employee packs remain untouched.
    """
    from app.infrastructure.mods.mod_manager import get_mod_manager

    bundle = bundled_mods_dir()
    if bundle is None:
        logger.info("seed_edition_mods: no bundled mods directory found")
        return []

    mm = get_mod_manager()
    root = Path(mods_root or mm.mods_root)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, str]] = []

    for mod_id in edition_mod_ids(edition):
        dst = root / mod_id
        src = _resolve_mod_seed_source(mod_id, bundle)
        if src is None:
            results.append(
                {
                    "mod_id": mod_id,
                    "status": "missing",
                    "message": f"not in bundle: {bundle / mod_id}",
                }
            )
            continue
        try:
            status, message = _refresh_bundled_mod(src, dst, root)
            results.append({"mod_id": mod_id, "status": status, "message": message})
        except OSError:
            results.append({"mod_id": mod_id, "status": "error", "message": "mod seed failed"})

    results.extend(_archive_retired_bundled_mods(root))
    results.extend(_seed_bundled_employee_packs(bundle, root))
    return results


__all__ = [
    "Edition",
    "resolve_edition",
    "should_register_host_legacy_routes",
    "edition_mod_ids",
    "configure_edition_defaults",
    "bundled_mods_dir",
    "seed_edition_mods_from_bundle",
]
