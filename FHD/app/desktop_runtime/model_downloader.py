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
from urllib.parse import urlsplit

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


def _safe_path_component(value: str, *, label: str) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 128 or raw in {".", ".."}:
        raise ValueError(f"invalid model {label}")
    if any(not (char.isalnum() or char in {"-", "_", "."}) for char in raw):
        raise ValueError(f"invalid model {label}")
    return raw


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


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        code = getcode()
        if isinstance(code, int):
            return code
    return 200


def _set_response_read_timeout(response: object, timeout: float) -> None:
    """Best-effort read timeout for urllib's HTTPResponse socket.

    urllib exposes only one timeout argument for connect + read. CPython's
    response object keeps the connected socket below ``fp.raw._sock``; keep
    this optional so alternate handlers and test doubles remain supported.
    """

    current = response
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            return
    settimeout = getattr(current, "settimeout", None)
    if callable(settimeout):
        settimeout(timeout)


def _content_range_start(value: str) -> int | None:
    # RFC 7233: "bytes 512-1023/2048"
    if not value.startswith("bytes ") or "-" not in value:
        return None
    first = value[6:].split("-", 1)[0]
    try:
        return int(first)
    except ValueError:
        return None


def _download_request(asset: ModelAsset, resume_from: int) -> urllib.request.Request:
    headers = {"User-Agent": "XCAGI-Desktop/7"}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
    return urllib.request.Request(asset.url, headers=headers)


def download_model(
    asset: ModelAsset,
    *,
    data_dir: str | os.PathLike[str] | None = None,
    progress: ProgressCallback | None = None,
    connect_timeout: float = 10.0,
    read_timeout: float = 60.0,
) -> Path:
    safe_name = _safe_path_component(asset.name, label="name")
    safe_version = _safe_path_component(asset.version, label="version")
    asset_filename = _safe_path_component(Path(urlsplit(asset.url).path).name, label="filename")
    target_dir = models_dir(data_dir) / safe_name / safe_version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset_filename
    partial = target.with_suffix(target.suffix + ".part")

    if target.exists() and _sha256(target).lower() == asset.sha256.lower():
        return target

    resume_from = partial.stat().st_size if partial.exists() else 0
    if asset.size and resume_from > asset.size:
        partial.unlink(missing_ok=True)
        resume_from = 0
    if asset.size and resume_from == asset.size:
        if _sha256(partial).lower() == asset.sha256.lower():
            os.replace(partial, target)
            return target
        partial.unlink(missing_ok=True)
        resume_from = 0

    if asset.size:
        remaining = max(asset.size - resume_from, 0)
        safety_margin = min(max(asset.size // 20, 16 * 1024 * 1024), 64 * 1024 * 1024)
        required_free = remaining + safety_margin
        free = shutil.disk_usage(target_dir).free
        if free < required_free:
            raise OSError(
                f"模型 {asset.name} 下载空间不足：需要至少 {required_free} bytes，"
                f"当前剩余 {free} bytes"
            )

    request = _download_request(asset, resume_from)
    response = urllib.request.urlopen(request, timeout=connect_timeout)
    try:
        status = _response_status(response)
        content_range = str(response.headers.get("Content-Range") or "")
        can_resume = (
            resume_from > 0 and status == 206 and _content_range_start(content_range) == resume_from
        )
        if resume_from > 0 and not can_resume:
            response.close()
            response = urllib.request.urlopen(
                _download_request(asset, 0),
                timeout=connect_timeout,
            )
            resume_from = 0

        _set_response_read_timeout(response, read_timeout)
        mode = "ab" if resume_from > 0 else "wb"
        copied = resume_from
        if asset.size:
            total = asset.size
        else:
            total = copied + int(response.headers.get("Content-Length") or 0)

        with partial.open(mode) as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(asset.name, copied, total)
    finally:
        response.close()

    if asset.size and partial.stat().st_size != asset.size:
        raise OSError(
            f"模型 {asset.name} 下载不完整：期望 {asset.size} bytes，"
            f"实际 {partial.stat().st_size} bytes"
        )

    digest = _sha256(partial)
    if digest.lower() != asset.sha256.lower():
        partial.unlink(missing_ok=True)
        raise ValueError(
            f"模型 {asset.name} 校验失败：期望 {asset.sha256[:12]}…，实际 {digest[:12]}…"
        )

    os.replace(partial, target)
    return target


def ensure_models(
    assets: Iterable[ModelAsset], *, data_dir: str | os.PathLike[str] | None = None
) -> list[Path]:
    return [download_model(asset, data_dir=data_dir) for asset in assets]
