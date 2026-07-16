"""Model download manifest and file downloader for desktop deployments."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .paths import ensure_desktop_dirs

ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ModelAsset:
    name: str
    version: str
    url: str
    sha256: str
    size: int | None = None


def models_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return ensure_desktop_dirs(data_dir)["models"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: str | os.PathLike[str]) -> list[ModelAsset]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assets = raw.get("models", raw)
    return [ModelAsset(**item) for item in assets]


def download_model(
    asset: ModelAsset,
    *,
    data_dir: str | os.PathLike[str] | None = None,
    progress: ProgressCallback | None = None,
    connect_timeout: float = 10.0,
    read_timeout: float = 60.0,
) -> Path:
    target_dir = models_dir(data_dir) / asset.name / asset.version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(asset.url).name
    partial = target.with_suffix(target.suffix + ".part")

    if target.exists() and _sha256(target).lower() == asset.sha256.lower():
        return target

    # 磁盘空间预检：至少 2x（临时文件 + 完整文件），避免下载中途磁盘满
    free = shutil.disk_usage(str(target_dir)).free
    needed = (asset.size or 0) * 2
    if needed and free < needed:
        raise OSError(
            f"磁盘剩余 {free} bytes,需要 {needed} bytes(模型 {asset.name} 需 2x 空间)"
        )

    # 断点续传：若 .part 已存在，基于其大小发 Range 请求
    resume_from = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "XCAGI-Desktop/7"}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    request = urllib.request.Request(asset.url, headers=headers)
    # urlopen 的 timeout 同时是连接和读取超时；通过 socket.settimeout 控制读取超时
    import socket

    with urllib.request.urlopen(request, timeout=connect_timeout) as response:
        status = getattr(response, "status", None) or response.getcode()
        if resume_from > 0 and status == 206:
            # 服务器支持续传：追加写入
            mode = "ab"
            content_range = response.headers.get("Content-Range", "")
            total = (
                int(content_range.split("/")[-1])
                if "/" in content_range
                else (asset.size or 0)
            )
            copied = resume_from
        else:
            # 服务器不支持 Range 或返回 200：从头开始
            mode = "wb"
            copied = 0
            total = asset.size or int(response.headers.get("Content-Length") or 0)
            resume_from = 0  # reset 以便后面写日志

        # 通过 raw socket 设置读取超时（urlopen 的 timeout 同时管连接和读取，无法独立）
        sock = response.fp.raw._sock if hasattr(response.fp, "raw") else None
        if sock is not None and hasattr(sock, "settimeout"):
            sock.settimeout(read_timeout)

        with partial.open(mode) as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(asset.name, copied, total)

    digest = _sha256(partial)
    if digest.lower() != asset.sha256.lower():
        partial.unlink(missing_ok=True)
        raise ValueError(
            f"模型 {asset.name} 校验失败:期望 {asset.sha256[:12]}…,实际 {digest[:12]}…"
        )

    shutil.move(str(partial), target)
    return target


def ensure_models(
    assets: Iterable[ModelAsset], *, data_dir: str | os.PathLike[str] | None = None
) -> list[Path]:
    return [download_model(asset, data_dir=data_dir) for asset in assets]
