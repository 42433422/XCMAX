"""在仓库编辑源 ``FHD/mods/`` 中定位 Mod 目录（兼容平铺与分层布局）。"""

from __future__ import annotations

from pathlib import Path

# 编辑源分层容器；运行时导出目录仍为平铺。
MOD_SOURCE_LAYERS = ("industry", "bridge", "employees", "tools")


def mod_source_dir(mod_id: str, *, repo_root: Path | None = None) -> Path | None:
    """返回含 manifest.json 的 Mod 目录；找不到返回 None。"""
    mid = (mod_id or "").strip()
    if not mid:
        return None
    root = (repo_root or Path(__file__).resolve().parents[2]) / "mods"
    direct = root / mid
    if (direct / "manifest.json").is_file():
        return direct
    for layer in MOD_SOURCE_LAYERS:
        candidate = root / layer / mid
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


__all__ = ["MOD_SOURCE_LAYERS", "mod_source_dir"]
