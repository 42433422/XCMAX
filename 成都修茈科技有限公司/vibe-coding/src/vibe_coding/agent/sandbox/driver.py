"""Driver-agnostic sandbox primitives.

Every concrete driver consumes the same :class:`SandboxJob` /
:class:`SandboxPolicy` pair and returns a :class:`SandboxResult`. This keeps
upstream code (skills runtime, tool runner, ProjectVibeCoder) decoupled from
where execution actually happens.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

JobKind = Literal["function", "command"]


@dataclass(slots=True)
class SandboxPolicy:
    """Declarative resource & capability policy applied to every job.

    Drivers translate these to the most appropriate native mechanism
    (RLIMITs for subprocess, ``--memory`` etc. for Docker). Unsupported
    fields degrade gracefully — the subprocess driver, for instance, can't
    drop network access on its own (callers should rely on the Docker driver
    when network isolation is a hard requirement).

    Resource fields (Docker mapping):

    - ``timeout_s`` — hard wall-clock cap.
    - ``memory_mb`` → ``--memory``.
    - ``memory_swap_mb`` → ``--memory-swap``. ``None`` defaults to the
      same value as ``memory_mb`` so the container can never use swap
      to bypass the RAM limit.
    - ``cpu_limit`` → ``--cpus`` (fractional). Combined with
      ``cpu_period_us`` / ``cpu_quota_us`` for cgroups v2 fine-grained
      control when set.
    - ``pids_limit`` → ``--pids-limit`` (caps fork bombs).
    - ``ulimits`` → repeated ``--ulimit`` flags. Defaults guard
      open-files (``nofile``) and userland process count (``nproc``);
      vendors can add ``fsize``, ``data``, etc.
    - ``tmpfs_size_mb`` → size of ``/tmp`` tmpfs mount (also applied
      to every entry in ``allow_write_paths`` outside ``/tmp``).
    - ``read_only_root`` / ``allow_write_paths`` — root filesystem
      protection.
    """

    timeout_s: float = 5.0
    memory_mb: int = 256
    memory_swap_mb: int | None = None
    cpu_limit: float = 1.0
    cpu_period_us: int = 0  # 0 = use Docker default; >0 for cgroups v2 quota
    cpu_quota_us: int = 0
    network: bool = False
    pids_limit: int = 64
    read_only_root: bool = True
    allow_write_paths: tuple[str, ...] = ("/tmp",)
    max_output_size: int = 10_000
    tmpfs_size_mb: int = 64
    ulimits: tuple[str, ...] = ("nofile=1024:1024", "nproc=64:64", "fsize=104857600")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allow_write_paths"] = list(self.allow_write_paths)
        d["ulimits"] = list(self.ulimits)
        return d

    def effective_memory_swap_mb(self) -> int:
        """``memory_swap_mb`` resolved to a concrete value.

        Docker treats ``--memory-swap == --memory`` as "no swap". We
        default to that to make the resource cap stick even on hosts
        with swap enabled.
        """
        if self.memory_swap_mb is None:
            return int(self.memory_mb)
        return int(self.memory_swap_mb)


@dataclass(slots=True)
class SandboxJob:
    """A single execution request.

    ``kind == "function"`` runs ``source_code`` in the sandbox interpreter
    and calls ``function_name(**input_data)``; the return value (coerced to
    a dict) becomes :attr:`SandboxResult.output`.

    ``kind == "command"`` runs ``command`` (a list, NEVER a shell string)
    inside ``workspace_dir`` (mounted into the container if applicable). The
    job's ``stdin`` payload is piped to the process. Use this for linters /
    type checkers / test runs.
    """

    kind: JobKind = "function"
    source_code: str = ""
    function_name: str = "run"
    input_data: dict[str, Any] = field(default_factory=dict)
    workspace_dir: str | None = None
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = ""
    image: str | None = None  # Docker image override; unused by subprocess
    allowed_imports: tuple[str, ...] | None = None
    description: str = ""


@dataclass(slots=True)
class SandboxResult:
    success: bool
    driver: str = "subprocess"
    output: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error_type: str = ""
    error_message: str = ""
    traceback_str: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class SandboxDriver(Protocol):
    """Minimum contract for any execution backend."""

    @property
    def name(self) -> str:  # pragma: no cover - trivial
        ...

    def is_available(self) -> bool:  # pragma: no cover - trivial
        ...

    def execute(  # pragma: no cover - protocol only
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult: ...


# ---------------------------------------------------------------------- helpers


def docker_available() -> bool:
    """``True`` when ``docker`` is on PATH and ``docker info`` succeeds."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def create_default_driver(
    *,
    prefer: Literal["auto", "docker", "subprocess"] = "auto",
    image: str = "python:3.11-slim",
) -> SandboxDriver:
    """Return the most isolating driver currently available.

    ``auto`` picks Docker when the daemon is reachable, otherwise falls back
    to subprocess. ``docker`` raises ``RuntimeError`` if Docker isn't
    available (use only when the caller has confirmed it is). ``subprocess``
    bypasses the Docker check entirely.
    """
    from .docker_driver import DockerSandboxDriver
    from .subprocess_driver import SubprocessSandboxDriver

    if prefer == "subprocess":
        return SubprocessSandboxDriver()
    if prefer == "docker":
        if not docker_available():
            raise RuntimeError("docker driver requested but `docker info` failed")
        return DockerSandboxDriver(image=image)
    if docker_available():
        return DockerSandboxDriver(image=image)
    return SubprocessSandboxDriver()


def resolve_workspace(workspace: str | Path | None) -> Path | None:
    """Validate a sandbox workspace path before using it.

    Rejects:

    - ``NUL`` bytes (some kernels treat them as path terminators)
    - non-existent or non-directory paths
    - filesystem roots (``/`` on POSIX, ``C:\\`` on Windows) — accidentally
      mounting the host root into a sandbox is one of the worst-case
      escapes; this guard makes the failure mode loud.

    On success returns the resolved ``Path`` (symlinks already followed by
    ``resolve()`` so the caller can use it directly).
    """
    if workspace is None:
        return None
    raw = str(workspace)
    if "\x00" in raw:
        raise ValueError("workspace_dir contains NUL byte")
    p = Path(workspace).resolve()
    if not p.is_dir():
        raise ValueError(f"workspace_dir {p!r} is not a directory")
    # ``Path.parent == Path`` is true exactly when ``p`` is a filesystem root.
    if p == p.parent:
        raise ValueError(
            f"workspace_dir {p!r} is a filesystem root; refusing to sandbox the host"
        )
    return p
