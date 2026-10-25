"""Manage startup logs and PID files for surface-audit services."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SurfaceProcessLauncher:
    pids_directory: Path
    logs_directory: Path

    def spawn(
        self,
        name: str,
        cmd: List[str],
        *,
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        pid_file = self.pids_directory / f"surface-audit-{name}.pid"
        if pid_file.is_file():
            try:
                old_pid = int(pid_file.read_text(encoding="utf-8").strip())
                if old_pid <= 1:
                    raise ValueError("invalid surface audit process id")
                os.kill(old_pid, 0)
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_running",
                    "pid": old_pid,
                }
            except (OSError, ValueError):
                pid_file.unlink(missing_ok=True)
        log_path = self.logs_directory / f"surface-audit-{name}.log"
        merged = {**os.environ, **(env or {})}
        with open(log_path, "a", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=merged,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid_file.write_text(str(proc.pid), encoding="utf-8")
        logger.info(
            "surface audit deps: started %s pid=%s cmd=%s",
            name,
            proc.pid,
            " ".join(cmd[:4]),
        )
        return {"ok": True, "started": True, "pid": proc.pid, "log": str(log_path)}


def _kill_pid_file(label: str, pid_file: Path) -> None:
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if pid <= 1:
            raise ValueError("invalid surface audit process id")
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 0)
    except OSError:
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 15)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, 9)
        except OSError:
            pass
        logger.info("surface audit deps: stopped %s pid=%s", label, pid)
    except OSError as exc:
        logger.warning("surface audit deps: stop %s pid=%s failed: %s", label, pid, exc)
    pid_file.unlink(missing_ok=True)


def stop_surface_audit_ephemeral(
    *,
    pids_directory: Path,
    fhd_directory: Path,
    stop_process: Callable[[str, Path], None],
) -> Dict[str, Any]:
    """关闭 ``ensure_surface_audit_deps`` 拉起的临时服务（不含 MODstore 日更栈）。"""
    stopped: List[str] = []
    pids_dir = pids_directory
    if pids_dir.is_dir():
        for pid_file in sorted(pids_dir.glob("surface-audit-*.pid")):
            if pid_file.name == "surface-audit-modstore.pid":
                continue
            stop_process(pid_file.stem, pid_file)
            stopped.append(pid_file.stem)
    emu_pid_raw = (os.environ.get("XCAGI_ANDROID_EMULATOR_PID_FILE") or "").strip()
    emu_pid = (
        Path(emu_pid_raw).expanduser().resolve()
        if emu_pid_raw
        else fhd_directory / "data" / "surface_audit" / ".android-emulator.pid"
    )
    if emu_pid.is_file():
        stop_process("android-emulator", emu_pid)
        stopped.append("android-emulator")
    return {"ok": True, "stopped": stopped}
