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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.desktop_runtime.migrate import export_config
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .paths import ensure_desktop_dirs, is_desktop_mode

logger = logging.getLogger(__name__)


def _redact_log_bytes(chunk: bytes) -> bytes:
    return redact_log_text(chunk.decode("utf-8", errors="replace")).encode(
        "utf-8", errors="replace"
    )[-250_000:]


def _tail_bytes(path: Path, max_bytes: int = 250_000) -> bytes | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - max_bytes))
            return f.read(max_bytes)
    except OSError as exc:
        logger.debug("failed to tail %s: %s", path, exc)
        return None


def build_support_bundle_zip(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    fastapi_version: str = "unknown",
) -> bytes:
    """Return ZIP bytes with non-secret diagnostics (no live DB copy)."""

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

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt", "清单不含密钥，日志已脱敏；数据库和崩溃转储不随包提供。\n".encode()
        )
        zf.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        )

        for name in (
            "xcagi.log",
            "xcagi.log.1",
            "xcagi.log.2",
            "electron-backend.log",
            "electron-backend.log.1",
        ):
            chunk = _tail_bytes(logs_dir / name)
            if chunk:
                zf.writestr(f"logs/{name}", _redact_log_bytes(chunk))

        if updater_chunk:
            zf.writestr("logs/updater-events.jsonl", _redact_log_bytes(updater_chunk))

    buf.seek(0)
    return buf.getvalue()


def build_evidence_ref(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    keep_last: int = 10,
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
        blob = build_support_bundle_zip(data_dir=data_dir)
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
        return {
            "kind": "support_bundle",
            "path": str(path),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            "generated_at": stamp,
        }
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        logger.debug("support bundle evidence build failed", exc_info=True)
        return None
