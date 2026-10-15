"""Build a ZIP support bundle for customer diagnostics (desktop mode only)."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import platform
import sys
import time
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.desktop_runtime.migrate import export_config
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .paths import ensure_desktop_dirs, is_desktop_mode

logger = logging.getLogger(__name__)
# MODstore customer issue intake rejects larger bundles.
SUPPORT_BUNDLE_MAX_BYTES = 256_000
_SCREENSHOT_BUDGET = 128_000
_SCREENSHOT_MAX_PIXELS = 40_000_000


def _redact_log_bytes(chunk: bytes) -> bytes:
    text = chunk.decode("utf-8", errors="replace")
    return redact_log_text(text).encode("utf-8", errors="replace")[-250_000:]


def _tail_bytes(path: Path, max_bytes: int = 250_000) -> bytes | None:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - max_bytes))
            return f.read(max_bytes)
    except OSError as exc:
        logger.debug("failed to tail %s: %s", path, exc)
        return None


def _fit_screenshots(images: Sequence[bytes]) -> list[bytes]:
    """Re-encode customer-selected screenshots as JPEG, shrinking them until they fit."""
    from PIL import Image

    frames = []
    for raw in images:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height <= _SCREENSHOT_MAX_PIXELS:
                    image.thumbnail((1600, 1600))
                    frames.append(image.convert("RGB"))
        except RECOVERABLE_ERRORS + (Image.DecompressionBombError,):
            logger.info("customer screenshot skipped", exc_info=True)
    shots: list[bytes] = []
    for side, quality in ((1600, 70), (1280, 60), (1024, 50), (800, 40)):
        shots = []
        for frame in frames:
            frame.thumbnail((side, side))
            out = io.BytesIO()
            frame.save(out, format="JPEG", quality=quality, optimize=True)
            shots.append(out.getvalue())
        if sum(map(len, shots)) <= _SCREENSHOT_BUDGET:
            return shots
    while sum(map(len, shots)) > _SCREENSHOT_BUDGET:
        shots.pop()
    return shots


def _zip_entries(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def build_support_bundle_zip(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    fastapi_version: str = "unknown",
    screenshots: Sequence[bytes] = (),
) -> bytes:
    """Return ZIP bytes with non-secret diagnostics (no live DB copy).

    ``screenshots`` are the images the customer attached to the report. The bundle stays
    within ``SUPPORT_BUNDLE_MAX_BYTES`` by dropping the oldest log lines first.
    """

    if not is_desktop_mode():
        raise RuntimeError("support bundle is only available in desktop mode")

    dirs = ensure_desktop_dirs(data_dir or os.environ.get("XCAGI_DATA_DIR"))
    dirs["root"]
    logs_dir = dirs["logs"]
    backups_dir = dirs["backups"]
    crash_dir = dirs["root"] / "crash-dumps"

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict[str, Any] = {
        "generatedAtUtc": stamp,
        "fastapiAppVersion": fastapi_version,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "desktopPaths": export_config(data_dir),
        "backupFiles": sorted(p.name for p in backups_dir.glob("*.db") if p.is_file())[-50:],
        "crashDumpFiles": sorted(p.name for p in crash_dir.glob("*") if p.is_file())[-50:],
        "note": "不含数据库正文；数据库备份请在 backups/ 目录单独拷贝。",
    }

    updater_log = logs_dir / "updater-events.jsonl"
    updater_chunk = _tail_bytes(updater_log, max_bytes=200_000)
    manifest["updaterLogIncluded"] = bool(updater_chunk)
    manifest["modsLoaded"] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        manifest["modsLoaded"] = [
            str(m.get("id") or "") for m in get_mod_manager().list_all_mods() if m.get("id")
        ][:200]
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        logger.warning("mod list for support bundle unavailable: %s", exc)
        manifest["modsLoaded"] = []

    shots: list[bytes] = []
    if screenshots:
        try:
            shots = _fit_screenshots(screenshots)
        except RECOVERABLE_ERRORS:
            logger.warning("customer screenshots unavailable for support bundle", exc_info=True)
        manifest["screenshots"] = {"selected": len(screenshots), "included": len(shots)}
    logs = [
        (f"logs/{name}", _redact_log_bytes(chunk))
        for name in (
            "xcagi.log",
            "xcagi.log.1",
            "xcagi.log.2",
            "electron-backend.log",
            "electron-backend.log.1",
        )
        if (chunk := _tail_bytes(logs_dir / name))
    ]
    if updater_chunk:
        logs.append(("logs/updater-events.jsonl", _redact_log_bytes(updater_chunk)))
    readme = "清单不含密钥，日志已脱敏；数据库和崩溃转储不随包提供。\n"
    if shots:
        readme += "screenshots/ 是客户报障时所选的截图，已压缩。\n"

    def pack(keep: int) -> bytes:
        return _zip_entries(
            [
                ("README.txt", readme.encode()),
                ("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode()),
                *((name, data[-keep:]) for name, data in logs),
                *((f"screenshots/{index}.jpg", shot) for index, shot in enumerate(shots, 1)),
            ]
        )

    keep = 250_000
    blob = pack(keep)
    while len(blob) > SUPPORT_BUNDLE_MAX_BYTES and keep >= 4_000:
        keep //= 2
        manifest["logTailBytes"] = keep
        blob = pack(keep)
    return blob


def build_evidence_ref(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    keep_last: int = 10,
    screenshots: Sequence[bytes] = (),
) -> dict[str, Any] | None:
    """落盘一份支持诊断包并返回工单 context 用的证据引用（best-effort）。

    连接件：客户信号 → 故障证据包。非桌面模式或构建失败一律返回 None，
    证据采集永不阻塞信号主线；引用只含路径/SHA256/大小，不含用户输入，
    与「提案字段精简、敏感输入不外泄」原则一致。
    """
    if not is_desktop_mode():
        return None
    try:
        dirs = ensure_desktop_dirs(data_dir or os.environ.get("XCAGI_DATA_DIR"))
        bundle_dir = dirs["root"] / "support-bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        blob = build_support_bundle_zip(data_dir=data_dir, screenshots=screenshots)
        stamp = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{time.time_ns() % 100000:05d}"
        path = bundle_dir / f"support-bundle-{stamp}.zip"
        path.write_bytes(blob)
        # 只保留最近 keep_last 份，防止诊断包目录无限膨胀
        bundles = sorted(bundle_dir.glob("support-bundle-*.zip"))
        for old in bundles[:-keep_last] if keep_last > 0 else []:
            try:
                old.unlink()
            except OSError:
                logger.debug("prune old support bundle failed: %s", old)
        ref: dict[str, Any] = {
            "kind": "support_bundle",
            "path": str(path),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            "generated_at": stamp,
        }
        if screenshots:
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                included = sum(name.startswith("screenshots/") for name in archive.namelist())
            ref["screenshots"] = {"selected": len(screenshots), "included": included}
        return ref
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        logger.debug("support bundle evidence build failed", exc_info=True)
        return None
