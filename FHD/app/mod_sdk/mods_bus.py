"""同 Mod 内 backend/ 目录下模块的文件路径式加载器（SDK re-export）。

``import_mod_backend_py(mod_path, mod_id, stem)`` 把 ``<mod_path>/backend/<stem>.py``
按独立 ``sys.modules`` 入口 ``_xcagi_mod_<mod_id>_<stem>`` 加载，避免多个 Mod
都叫 ``services`` / ``blueprints`` 时相互覆盖。
"""

from __future__ import annotations

from typing import cast

from app.infrastructure.mods.mod_manager import (
    get_mod_manager,
    import_mod_backend_py,
)


def resolve_mod_directory(mod_id: str) -> str | None:
    """Resolve an installed MOD directory without exposing host internals to packs."""
    return cast("str | None", get_mod_manager().resolve_mod_directory(mod_id))


__all__ = ["import_mod_backend_py", "resolve_mod_directory"]
