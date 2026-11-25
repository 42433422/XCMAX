"""Launch the SDK-owned runtime with an explicit environment, never the host's.

The upstream SDK merges its ``env`` into ``os.environ``. This small exec wrapper
is needed until it supports replacement environments. It changes no environment
in the XCMAX process and contains no JSON-RPC implementation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def verify_installation() -> None:
    """Verify the pinned SDK, CLI package and its actual bundled executable."""
    import importlib
    import subprocess
    from importlib.metadata import version

    import openai_codex

    from app.infrastructure.xiaox.policy import CODEX_VERSION

    if (
        openai_codex.__version__ != CODEX_VERSION
        or version("openai-codex-cli-bin") != CODEX_VERSION
    ):
        raise RuntimeError(f"Pinned Xiaox SDK and CLI {CODEX_VERSION} are required")
    bundled = importlib.import_module("codex_cli_bin")
    runtime = subprocess.run(
        [str(bundled.bundled_codex_path()), "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    if runtime.stdout.strip() != f"codex-cli {CODEX_VERSION}":
        raise RuntimeError("Installed Xiaox executable version mismatch")


def runtime_environment(plan: dict) -> dict[str, str]:
    state = Path(plan["state_dir"])
    env = {
        "PATH": os.pathsep.join((str(Path(plan["binary"]).parent), os.defpath)),
        "CODEX_HOME": str(state),
        "XDG_CONFIG_HOME": str(state / "config"),
        "XDG_DATA_HOME": str(state / "data"),
        "XDG_CACHE_HOME": str(state / "cache"),
        "TMPDIR": str(state / "tmp"),
        "TMP": str(state / "tmp"),
        "TEMP": str(state / "tmp"),
        "XCMAX_XIAOX_PROVIDER_KEY": plan["provider_token"],
        "XCMAX_XIAOX_MCP_TOKEN": plan["mcp_token"],
        # The model/MCP endpoints are private loopback. Some HTTP clients read a
        # host-wide system proxy without honouring its loopback exceptions, which
        # turns every local call into a proxy 502. Pin an explicit bypass.
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
    }
    # Windows needs these OS locations to load system libraries. No inherited
    # PATH, proxy, Python, Xiaox, cloud-account or provider credential is copied.
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR"):
            value = os.environ.get(key)
            if value:
                env[key] = value
    return env


def launch_arguments(plan_path: Path) -> tuple[str, ...]:
    """Re-enter a frozen backend before server/bootstrap imports, or use Python."""
    if getattr(sys, "frozen", False):
        return (sys.executable, "--xcagi-xiaox-launch", str(plan_path))
    return (sys.executable, "-I", str(Path(__file__).resolve()), str(plan_path))


def _windows_kernel() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Windows process APIs are unavailable")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetStdHandle": ([wintypes.DWORD], wintypes.HANDLE),
        "GetFileType": ([wintypes.HANDLE], wintypes.DWORD),
        "SetDllDirectoryW": ([wintypes.LPCWSTR], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _windows_job_limits() -> Any:
    import ctypes as c

    # Windows ABI: DWORD/ULONGLONG have fixed widths, SIZE_T follows the process.
    # https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
    class BasicLimits(c.Structure):
        _fields_ = [
            ("process_time", c.c_int64),
            ("job_time", c.c_int64),
            ("flags", c.c_uint32),
            ("minimum_working_set", c.c_size_t),
            ("maximum_working_set", c.c_size_t),
            ("active_processes", c.c_uint32),
            ("affinity", c.c_size_t),
            ("priority", c.c_uint32),
            ("scheduling", c.c_uint32),
        ]

    class ExtendedLimits(c.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io_counters", c.c_uint64 * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process_memory", c.c_size_t),
            ("peak_job_memory", c.c_size_t),
        ]

    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return limits


class WindowsRuntimeJob:
    """One SDK transport owns one OS job; this object never routes protocol I/O."""

    name: str

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows process jobs are unavailable")
        import ctypes
        import secrets

        self.name = "Local\\XCMAX-Xiaox-" + secrets.token_hex(16)
        self._kernel = _windows_kernel()
        ctypes.set_last_error(0)
        self._handle = self._kernel.CreateJobObjectW(None, self.name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            self._kernel.CloseHandle(self._handle)
            self._handle = None
            raise OSError("Xiaox process job already exists")
        limits = _windows_job_limits()
        if not self._kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self._kernel.CloseHandle(self._handle)
            self._handle = None
            raise error

    def close(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows process jobs are unavailable")
        import ctypes

        handle, self._handle = self._handle, None
        if handle:
            try:
                if not self._kernel.TerminateJobObject(handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self._kernel.CloseHandle(handle)


def _launch_state(plan: dict, phase: str, **details: Any) -> None:
    # Diagnostic fields are only local PIDs, pipe availability and error codes.
    # Never record the launch plan, environment, credentials or SDK messages.
    (Path(plan["state_dir"]) / "launcher-status.json").write_text(
        json.dumps({"phase": phase, "launcher_pid": os.getpid(), **details}), encoding="utf-8"
    )


def _run_windows(plan: dict, binary: str, env: dict[str, str]) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows launcher is unavailable")
    import ctypes
    import subprocess

    kernel = _windows_kernel()
    _launch_state(plan, "enter")
    try:
        # The owner is the SDK host, outside this job. Join before creating the
        # CLI; descendants inherit membership and cannot outlive host cleanup.
        # https://learn.microsoft.com/windows/win32/procthread/job-objects
        job = kernel.OpenJobObjectW(0x0001, False, plan["job_name"])
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(job)
        if getattr(sys, "frozen", False) and not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        handles = [kernel.GetStdHandle(number) for number in (-10, -11, -12)]
        pipes = [bool(handle) and kernel.GetFileType(handle) == 3 for handle in handles]
        _launch_state(plan, "stdio", stdio_pipes=pipes)
        if not all(pipes):
            raise OSError("Xiaox launcher requires the SDK's three standard pipes")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
        startup.lpAttributeList = {"handle_list": handles}
        inherited = [os.get_handle_inheritable(handle) for handle in handles]
        try:
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            process = subprocess.Popen(
                [binary, "app-server", "--listen", "stdio://"],
                env=env,
                cwd=plan["workspace"],
                startupinfo=startup,
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        finally:
            for handle, previous in zip(handles, inherited, strict=True):
                os.set_handle_inheritable(handle, previous)
        _launch_state(plan, "cli_started", stdio_pipes=pipes, cli_pid=process.pid)
        raise SystemExit(process.wait())
    except OSError as exc:
        _launch_state(
            plan, "failed", error=type(exc).__name__, winerror=getattr(exc, "winerror", None)
        )
        # An unhandled exception in a windowed bootloader opens a blocking dialog.
        raise SystemExit(1) from exc


def main(plan_file: str | None = None) -> None:
    plan_path = Path(plan_file or sys.argv[1])
    if not plan_path.is_absolute() or plan_path.is_symlink():
        raise SystemExit("Xiaox launch configuration must be an absolute private file")
    if os.name != "nt" and plan_path.stat().st_mode & 0o077:
        raise SystemExit("Xiaox launch configuration must be private")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    binary = str(Path(plan["binary"]).resolve(strict=True))
    env = runtime_environment(plan)
    if sys.platform == "win32":
        _run_windows(plan, binary, env)
        return
    # Only the controlled workspace is visible as cwd. Instruction discovery is
    # separately disabled in config; parent-repository AGENTS.md is not loaded.
    os.chdir(plan["workspace"])
    os.execve(binary, [binary, "app-server", "--listen", "stdio://"], env)


if __name__ == "__main__":
    main()
