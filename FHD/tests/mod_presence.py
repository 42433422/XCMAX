"""桥接 mod 物理目录存在性辅助。

平台桥接 mod（xcagi-*-bridge 等）的物理目录是**可选打包产物**：facade 逻辑由
``app/mod_sdk/*_compat.py`` 提供，不依赖物理 ``mods/<id>/``。本仓库 checkout 默认不
含这些物理目录（git 历史从未跟踪），因此「读取物理 manifest/blueprints」类断言在此
环境不适用——应 **skip 而非 fail**，同时保留同文件内的纯逻辑用例。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def skip_if_bridge_mod_absent(mod_id: str) -> Path:
    """物理桥接 mod 缺失即 ``pytest.skip``；存在则返回其目录路径。"""
    mod_dir = REPO / "mods" / mod_id
    if not mod_dir.is_dir():
        pytest.skip(f"physical bridge mod '{mod_id}' not present in this repo checkout")
    return mod_dir
