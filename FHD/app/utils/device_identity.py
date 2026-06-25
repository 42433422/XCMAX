"""稳定设备标识：一次生成、落盘、跨重启 / 换端口 / 更新不变。

设备标识必须是**身份**而非**标签**。旧实现用 ``hostname:port``，换端口或改主机名
就被当成新设备，导致中继重复注册、配对错位。这里生成一次 UUID 落到 app data dir
（应用更新保留该目录），之后恒定返回；``hostname:port`` 退化为人类可读的
label / capabilities（不再承担身份）。

重启语义见 docs/account_system_ssot.md §十。
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_DEVICE_ID_FILENAME = "device_id"
_lock = threading.Lock()
_cached: str | None = None


def _device_id_path() -> Path:
    return Path(get_app_data_dir()) / _DEVICE_ID_FILENAME


def get_stable_device_id() -> str:
    """返回本机稳定设备 UUID（hex）；不存在则生成并落盘。

    - ``XCAGI_DEVICE_ID`` 环境变量可显式覆盖（容器 / 测试）。
    - 读写失败（只读 FS 等）回退到进程内随机值（不落盘），保证永不抛错、永不返回空。
    """
    override = os.environ.get("XCAGI_DEVICE_ID", "").strip()
    if override:
        return override

    global _cached
    with _lock:
        if _cached:
            return _cached

        path = _device_id_path()
        try:
            if path.is_file():
                existing = path.read_text(encoding="utf-8").strip()
                if existing:
                    _cached = existing
                    return _cached
        except OSError:
            logger.warning("device_id 读取失败，将尝试重建：%s", path, exc_info=True)

        new_id = uuid.uuid4().hex
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_id + "\n", encoding="utf-8")
        except OSError:
            # 落盘失败：本进程用临时值兜底，不抛错（下次进程会再尝试落盘）。
            logger.warning("device_id 落盘失败，本进程使用临时设备标识：%s", path, exc_info=True)
        _cached = new_id
        return _cached
