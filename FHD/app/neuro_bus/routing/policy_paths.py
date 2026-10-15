"""桌面路由策略写入 userData，读取回退 bundle 种子，避免破坏 codesign 封条。"""

from __future__ import annotations

import os
from pathlib import Path

# 仓库/bundle 内置目录（种子数据，只读用途）
BUNDLED_POLICIES_DIR = Path(__file__).resolve().parents[3] / "resources" / "routing_policies"

ENV_DIR = "XCAGI_ROUTING_POLICIES_DIR"


def writable_policies_dir() -> Path:
    """可写目录：env 覆盖 > 桌面 userData > 开发态仓库目录。"""
    override = (os.environ.get(ENV_DIR) or "").strip()
    if override:
        return Path(override).expanduser()
    from app.desktop_runtime.paths import get_desktop_data_dir, is_desktop_mode

    if is_desktop_mode():
        return get_desktop_data_dir() / "data" / "routing_policies"
    return BUNDLED_POLICIES_DIR


def resolve_policy_file(name: str, *, for_write: bool = False) -> Path:
    """写入时创建可写目录；读取优先 userData、回退种子，均缺失则返回可写路径。"""
    if for_write:
        target_dir = writable_policies_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / name
    candidate = writable_policies_dir() / name
    if candidate.is_file():
        return candidate
    bundled = BUNDLED_POLICIES_DIR / name
    return bundled if bundled.is_file() else candidate
