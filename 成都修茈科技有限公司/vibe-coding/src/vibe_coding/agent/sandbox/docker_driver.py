"""Docker-backed :class:`SandboxDriver`.

Implements true container-level isolation by shelling out to the ``docker``
CLI (no Python ``docker`` package required, so it works as soon as Docker
Desktop / Engine is installed). Per-job we run::

    docker run --rm \\
        --network=<none|bridge> --read-only \\
        --memory=<mb>m --cpus=<n> --pids-limit=<n> \\
        --cap-drop=ALL --security-opt=no-new-privileges \\
        --tmpfs /tmp:rw,size=64m \\
        --volume <workspace>:/work:<ro|rw> \\
        --workdir /work \\
        <image> \\
        <command>

For ``function`` jobs we synthesise a tiny bootstrap script that compiles
``source_code`` with the same restricted builtins enforced by the
subprocess driver, calls ``function_name(**input_data)``, and prints the
result as JSON. The bootstrap is mounted from a temp dir into ``/work`` and
removed when the call returns.

When Docker is unavailable :meth:`DockerSandboxDriver.is_available` returns
``False`` and ``execute`` will return an error instead of raising — leave
fallback selection to :func:`create_default_driver`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from .driver import SandboxJob, SandboxPolicy, SandboxResult, docker_available, resolve_workspace

DEFAULT_IMAGE = "python:3.11-slim"


class DockerSandboxDriver:
    """``docker run`` — based driver with strict resource & capability limits."""

    name = "docker"

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        docker_bin: str = "docker",
        extra_run_args: tuple[str, ...] = (),
    ) -> None:
        self.image = image
        self.docker_bin = docker_bin
        self.extra_run_args = tuple(extra_run_args)

    def is_available(self) -> bool:
        return docker_available()

    # ----------------------------------------------------------------- public

    def execute(
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        if not self.is_available():
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="RuntimeError",
                error_message="docker daemon is not reachable",
            )
        pol = policy or SandboxPolicy()
        image = job.image or self.image
        if job.kind == "function":
            return self._execute_function(job, pol, image)
        if job.kind == "command":
            return self._execute_command(job, pol, image)
        return SandboxResult(
            success=False,
            driver=self.name,
            error_type="ValueError",
            error_message=f"unknown job kind {job.kind!r}",
        )

    # --------------------------------------------------------------- function

    def _execute_function(
        self,
        job: SandboxJob,
        pol: SandboxPolicy,
        image: str,
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="vibe-sandbox-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "user_code.py").write_text(job.source_code, encoding="utf-8")
            (tmp_path / "input.json").write_text(
                json.dumps(job.input_data, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            allowed = list(job.allowed_imports) if job.allowed_imports is not None else _DEFAULT_ALLOWED
            (tmp_path / "bootstrap.py").write_text(
                _BOOTSTRAP_TEMPLATE.format(
                    function_name=job.function_name,
                    max_output_size=int(pol.max_output_size),
                    allowed=json.dumps(sorted(allowed)),
                ),
                encoding="utf-8",
            )

            command = ["python", "/work/bootstrap.py"]
            run_args = self._build_run_args(
                pol=pol,
                workspace=tmp_path,
                read_only_workspace=True,
                image=image,
            )
            t0 = time.perf_counter()
            proc = self._run(run_args + command, timeout=pol.timeout_s, env=job.env)
            elapsed = round((time.perf_counter() - t0) * 1000, 3)

            if proc.timed_out:
                return SandboxResult(
                    success=False,
                    driver=self.name,
                    error_type="TimeoutError",
                    error_message=f"docker job timed out after {pol.timeout_s}s",
                    stdout=_truncate(proc.stdout, pol.max_output_size),
                    stderr=_truncate(proc.stderr, pol.max_output_size),
                    exit_code=proc.exit_code,
                    duration_ms=elapsed,
                )

            payload = _extract_json(proc.stdout)
            if payload is None:
                return SandboxResult(
                    success=False,
                    driver=self.name,
                    error_type="RuntimeError",
                    error_message="bootstrap returned no JSON payload",
                    stdout=_truncate(proc.stdout, pol.max_output_size),
                    stderr=_truncate(proc.stderr, pol.max_output_size),
                    exit_code=proc.exit_code,
                    duration_ms=elapsed,
                )

            return SandboxResult(
                success=bool(payload.get("success")),
                driver=self.name,
                output=dict(payload.get("output") or {}),
                error_type=str(payload.get("error_type") or ""),
                error_message=str(payload.get("error_message") or ""),
                traceback_str=str(payload.get("traceback_str") or ""),
                duration_ms=float(payload.get("duration_ms") or elapsed),
                exit_code=proc.exit_code,
                stderr=_truncate(proc.stderr, pol.max_output_size),
            )

    # ---------------------------------------------------------------- command

    def _execute_command(
        self,
        job: SandboxJob,
        pol: SandboxPolicy,
        image: str,
    ) -> SandboxResult:
        if not job.command:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="ValueError",
                error_message="command job requires non-empty `command`",
            )
        try:
            workspace = resolve_workspace(job.workspace_dir)
        except ValueError as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="ValueError",
                error_message=str(exc),
            )
        if workspace is None:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="ValueError",
                error_message="command job requires `workspace_dir`",
            )

        run_args = self._build_run_args(
            pol=pol,
            workspace=workspace,
            read_only_workspace=pol.read_only_root,
            image=image,
        )
        t0 = time.perf_counter()
        proc = self._run(
            run_args + list(job.command),
            timeout=pol.timeout_s,
            env=job.env,
            stdin=job.stdin or None,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        return SandboxResult(
            success=(not proc.timed_out) and proc.exit_code == 0,
            driver=self.name,
            stdout=_truncate(proc.stdout, pol.max_output_size),
            stderr=_truncate(proc.stderr, pol.max_output_size),
            exit_code=proc.exit_code,
            error_type="TimeoutError" if proc.timed_out else "",
            error_message=(
                f"docker job timed out after {pol.timeout_s}s" if proc.timed_out else ""
            ),
            duration_ms=elapsed,
        )

    # --------------------------------------------------------------- internals

    def _build_run_args(
        self,
        *,
        pol: SandboxPolicy,
        workspace: Path,
        read_only_workspace: bool,
        image: str,
    ) -> list[str]:
        ws_flag = "ro" if read_only_workspace else "rw"
        tmpfs_size = max(8, int(getattr(pol, "tmpfs_size_mb", 64)))
        args: list[str] = [
            self.docker_bin,
            "run",
            "--rm",
            "-i",
            f"--network={'bridge' if pol.network else 'none'}",
            f"--memory={int(pol.memory_mb)}m",
            f"--memory-swap={int(pol.effective_memory_swap_mb())}m",
            # ``--memory-swappiness=0`` discourages the kernel from
            # swapping anonymous pages even if the host has swap enabled.
            "--memory-swappiness=0",
            f"--cpus={pol.cpu_limit:.2f}",
            f"--pids-limit={int(pol.pids_limit)}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--tmpfs=/tmp:rw,size={tmpfs_size}m",
        ]
        # cgroups v2 fine-grained CPU quota — only set when the caller
        # explicitly asked. ``--cpus`` already covers the common case.
        if pol.cpu_period_us > 0:
            args.append(f"--cpu-period={int(pol.cpu_period_us)}")
        if pol.cpu_quota_us > 0:
            args.append(f"--cpu-quota={int(pol.cpu_quota_us)}")
        # Ulimits: nofile / nproc / fsize protect against runaway file
        # descriptors / fork-bombs / huge writes.
        for ulimit in pol.ulimits:
            spec = str(ulimit).strip()
            if spec:
                args.extend(["--ulimit", spec])
        if pol.read_only_root:
            args.append("--read-only")
        args.extend(
            [
                "--volume",
                f"{_docker_path(workspace)}:/work:{ws_flag}",
                "--workdir",
                "/work",
            ]
        )
        # Extra writable tmpfs mounts honour the policy's tmpfs_size_mb,
        # capped at 64 MiB each so a misconfig can't blow up the host.
        per_path_mb = min(tmpfs_size, 64)
        for path in pol.allow_write_paths:
            if path == "/tmp":
                continue
            args.extend(["--tmpfs", f"{path}:rw,size={per_path_mb}m"])
        args.extend(self.extra_run_args)
        args.append(image)
        return args

    def _run(
        self,
        argv: list[str],
        *,
        timeout: float,
        env: dict[str, str] | None,
        stdin: str | None = None,
    ) -> "_RawProc":
        merged_env = os.environ.copy()
        if env:
            merged_env.update({k: str(v) for k, v in env.items()})
        try:
            proc = subprocess.run(
                argv,
                env=merged_env,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=timeout + 5,
                check=False,
            )
            return _RawProc(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=int(proc.returncode),
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _RawProc(
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                exit_code=-1,
                timed_out=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return _RawProc(
                stdout="",
                stderr=f"docker invocation failed: {exc}",
                exit_code=-1,
                timed_out=False,
            )


# ---------------------------------------------------------------------- helpers


class _RawProc:
    __slots__ = ("stdout", "stderr", "exit_code", "timed_out")

    def __init__(self, *, stdout: str, stderr: str, exit_code: int, timed_out: bool) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated {len(text) - limit} chars ...]"


def _docker_path(path: Path) -> str:
    """Translate a host path to the form expected by ``docker -v`` mounts.

    On Windows that means ``C:\\foo`` → ``/c/foo`` (the format Docker Desktop
    accepts). On POSIX we hand the absolute path back unchanged.
    """
    abs_path = str(path.resolve())
    if os.name == "nt":
        drive, rest = os.path.splitdrive(abs_path)
        if drive and len(drive) >= 2:
            letter = drive[0].lower()
            normalised = rest.replace("\\", "/")
            if not normalised.startswith("/"):
                normalised = "/" + normalised
            return f"/{letter}{normalised}"
    return abs_path


def _extract_json(stdout: str) -> dict[str, Any] | None:
    """Locate the bootstrap's JSON payload anywhere in stdout.

    Mirrors the strict→lenient cascade of :func:`vibe_coding.nl.parsing`
    but lives here so the sandbox driver stays self-contained (it must
    work even if ``vibe_coding.nl`` ever fails to import inside the
    container's bootstrap-generated wrapper).
    """
    text = (stdout or "").strip()
    if not text:
        return None
    # Strict pass.
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    # Walk every ``{`` candidate looking for a fully decodable object.
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx >= 0:
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            return obj
        idx = text.find("{", idx + 1)
    # Last-resort: try the shared tolerant parser; ignore failures.
    try:
        from ...nl.parsing import safe_parse_json_object

        return safe_parse_json_object(text)
    except Exception:  # noqa: BLE001
        return None


_DEFAULT_ALLOWED: list[str] = [
    "json",
    "re",
    "math",
    "datetime",
    "collections",
    "itertools",
    "functools",
    "typing",
    "dataclasses",
    "copy",
]


_BOOTSTRAP_TEMPLATE = textwrap.dedent(
    """\
    import json, sys, time, traceback, builtins as _b

    SAFE_NAMES = {{
        "bool","bytes","bytearray","complex","dict","float","frozenset","int",
        "list","object","set","slice","str","tuple","type","abs","all","any",
        "callable","chr","divmod","enumerate","filter","format","hasattr",
        "hash","hex","id","isinstance","issubclass","iter","len","map","max",
        "min","next","oct","ord","pow","print","range","repr","reversed",
        "round","sorted","sum","zip","ArithmeticError","AssertionError",
        "AttributeError","BaseException","Exception","IndexError","KeyError",
        "LookupError","NotImplementedError","RuntimeError","StopIteration",
        "TypeError","ValueError","ZeroDivisionError","True","False","None",
        "NotImplemented","Ellipsis"
    }}
    ALLOWED = set({allowed})

    safe = {{name: getattr(_b, name) for name in SAFE_NAMES if hasattr(_b, name)}}
    real_import = _b.__import__

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = (name or "").split(".")[0]
        if level and level > 0:
            raise ImportError("relative imports not allowed in sandbox")
        if root not in ALLOWED:
            raise ImportError(f"import of {{name!r}} is not allowed")
        return real_import(name, globals, locals, fromlist, level)

    safe["__import__"] = restricted_import

    with open("/work/user_code.py", encoding="utf-8") as fh:
        source = fh.read()
    with open("/work/input.json", encoding="utf-8") as fh:
        input_data = json.load(fh)

    t0 = time.perf_counter()
    out = {{
        "success": False,
        "output": {{}},
        "error_type": "",
        "error_message": "",
        "traceback_str": "",
        "duration_ms": 0.0,
    }}
    try:
        ns = {{"__builtins__": safe}}
        exec(compile(source, "<sandbox>", "exec"), ns, ns)
        fn = ns.get({function_name!r})
        if not callable(fn):
            raise RuntimeError(f"function {{!r}} not found".format({function_name!r}))
        result = fn(**input_data)
        result_dict = result if isinstance(result, dict) else {{"result": result}}
        raw = json.dumps(result_dict, default=str, ensure_ascii=False)
        if len(raw) > {max_output_size}:
            raise ValueError(f"output too large: {{len(raw)}} > {max_output_size}")
        out["success"] = True
        out["output"] = result_dict
    except Exception as exc:
        out["error_type"] = type(exc).__name__
        out["error_message"] = str(exc)
        out["traceback_str"] = traceback.format_exc()
    finally:
        out["duration_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        sys.stdout.flush()
    """
)


__all__ = ["DEFAULT_IMAGE", "DockerSandboxDriver"]


# --- Trivial references for type-checkers --------------------------------
_ = (shutil, Any)  # noqa: F841
