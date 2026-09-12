"""路由策略文件路径解析。

桌面打包（PyInstaller）场景下，``__file__`` 相对路径落在签名 bundle 内
（macOS: ``*.app/Contents/Resources/backend/_internal/...``）。运行期写入
（在线学习权重/manifest、路由决策日志、plan graph 日志）会破坏 codesign
封条，导致 Gatekeeper 拒签。因此桌面模式下所有写入一律重定向到 userData
（``~/Library/Application Support/XCAGI/data/routing_policies``），读取则
优先 userData、回退 bundle 内置种子文件。
"""

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
    """解析策略文件路径。

    for_write=True：返回可写目录内路径（必要时建目录）。
    for_write=False：userData 存在则用 userData，否则回退 bundle 种子；
    两者都不存在时返回可写目录内路径（调用方按缺失处理）。
    """
    if for_write:
        target_dir = writable_policies_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / name
    candidate = writable_policies_dir() / name
    if candidate.is_file():
        return candidate
    bundled = BUNDLED_POLICIES_DIR / name
    return bundled if bundled.is_file() else candidate
