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
        "XCMAX_CODEX_PROVIDER_KEY": plan["provider_token"],
        "XCMAX_CODEX_MCP_TOKEN": plan["mcp_token"],
    }
    # Windows needs these OS locations to load system libraries. No inherited
    # PATH, proxy, Python, Codex, cloud-account or provider credential is copied.
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR"):
            value = os.environ.get(key)
            if value:
                env[key] = value
    return env


def launch_arguments(plan_path: Path) -> tuple[str, ...]:
    """Re-enter a frozen backend before server/bootstrap imports, or use Python."""
    if getattr(sys, "frozen", False):
        return (sys.executable, "--xcagi-codex-launch", str(plan_path))
    return (sys.executable, "-I", str(Path(__file__).resolve()), str(plan_path))


def main(plan_file: str | None = None) -> None:
    plan_path = Path(plan_file or sys.argv[1])
    if not plan_path.is_absolute() or plan_path.is_symlink():
        raise SystemExit("Codex launch configuration must be an absolute private file")
    if os.name != "nt" and plan_path.stat().st_mode & 0o077:
        raise SystemExit("Codex launch configuration must be private")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    binary = str(Path(plan["binary"]).resolve(strict=True))
    env = runtime_environment(plan)
    # A frozen Windows host changes the process DLL search directory. The CLI
    # is an independent binary and must load its own/system libraries.
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
    # Only the controlled workspace is visible as cwd. Instruction discovery is
    # separately disabled in config; parent-repository AGENTS.md is not loaded.
    os.chdir(plan["workspace"])
    os.execve(binary, [binary, "app-server", "--listen", "stdio://"], env)


if __name__ == "__main__":
    main()
