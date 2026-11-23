"""Configure the existing pinned native boundary for business replay workers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def sandbox_command(directory, env, policy_path, *, support, project, worker_module, timeout=60):
    """Configure the existing pinned boundary before any employee can start."""
    configured_entry = os.environ.get("PROMPTFOO_SANDBOX_ENTRY") or str(
        support.parent
        / "capability_trainer_deps/node_modules/@anthropic-ai/sandbox-runtime/dist/cli.js"
    )
    entry = Path(configured_entry).expanduser().resolve(strict=True)
    if entry.name not in {"cli.js", "index.js"} or entry.parent.name != "dist":
        raise ValueError("training_replay_sandbox_required")
    entry = entry.with_name("cli.js").resolve(strict=True)
    node = shutil.which("node", path=env.get("PATH", os.defpath))
    if not node:
        raise ValueError("training_replay_sandbox_required")
    node = str(Path(node).resolve(strict=True))
    # Keep the public host/version admission and policy implementation. This is
    # trusted configuration only; the model-facing assertion defers native replay.
    configured = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            "const {openCodeSandboxEntry, sandboxSettings}=await import(process.argv[1]); "
            "const runtime=openCodeSandboxEntry({DEVFLEET_OPENCODE_SANDBOX_ENTRY:process.argv[4]}); "
            "if (!runtime) throw Error('training_replay_sandbox_unavailable'); "
            "process.stdout.write(JSON.stringify({runtime, node:process.execPath, arch:process.arch, "
            "policy:sandboxSettings(process.argv[2], process.argv[2], process.argv[3], "
            "process.execPath, new URL('https://offline.invalid'), false, runtime)}));",
            support.as_uri(),
            str(directory),
            sys.executable,
            str(entry),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    if configured.returncode:
        raise ValueError("training_replay_sandbox_unavailable")
    settings = json.loads(configured.stdout)
    if settings.get("runtime") != str(entry) or settings.get("node") != node:
        raise ValueError("training_replay_sandbox_identity_changed")
    policy = settings["policy"]
    policy["network"] = {
        "allowedDomains": [],
        "deniedDomains": ["*"],
        "strictAllowlist": True,
        "allowUnixSockets": [],
        "allowAllUnixSockets": False,
        "allowLocalBinding": False,
    }
    policy.update(
        allowNestedUserNamespaces=False,
        enableWeakerNestedSandbox=False,
        enableWeakerNetworkIsolation=False,
    )
    code_roots = (
        project / "modstore_server",
        project / "modman",
        project.parents[1] / "FHD/app",
    )
    readable = [
        str(directory),
        sys.executable,
        str(Path(sys.executable).resolve()),
        str(Path(sys.prefix) / "pyvenv.cfg"),
        *(sysconfig.get_path(key) for key in ("stdlib", "platstdlib", "purelib", "platlib")),
        *(str(path) for path in code_roots),
    ]
    # setup-python and framework builds can load shared runtimes outside /usr.
    # Allow the installed library files, never the surrounding customer directory.
    for parent in (sysconfig.get_config_var("LIBDIR"), str(Path(sys.base_prefix) / "lib")):
        if parent:
            for name in (
                sysconfig.get_config_var("LDLIBRARY"),
                sysconfig.get_config_var("INSTSONAME"),
            ):
                if name:
                    library = Path(parent) / name
                    if library.is_file():
                        readable.extend((str(library), str(library.resolve())))
    framework = sysconfig.get_config_var("PYTHONFRAMEWORK")
    if framework:
        library = Path(sys.base_prefix) / framework
        if library.is_file():
            readable.extend((str(library), str(library.resolve())))
    if sys.platform == "linux":
        seccomp = entry.parents[1] / "vendor/seccomp" / settings["arch"] / "apply-seccomp"
        if not seccomp.is_file() or not os.access(seccomp, os.X_OK):
            raise ValueError("training_replay_sandbox_unavailable")
        policy["seccomp"] = {"applyPath": str(seccomp)}
        readable.append(str(seccomp))
    policy["filesystem"]["allowRead"] = sorted(
        set(policy["filesystem"]["allowRead"])
        | {path for path in readable if path and Path(path).exists()}
    )
    policy["filesystem"]["allowWrite"] = [str(directory)]
    # Mount code directories once, preserving the public specific state denies.
    # Per-file source globs exceed the fixed runtime's mount limit.
    policy["filesystem"].setdefault("denyRead", []).extend(
        str(code_roots[0] / name)
        for name in (
            "catalog_data",
            "data",
            "market_files",
            "payment_orders",
            "webhook_events",
            "workbench_script_runs",
            "backups",
            "tests",
        )
    )
    policy["filesystem"]["denyRead"].extend(
        str(root / "**" / pattern)
        for root in code_roots
        for pattern in (
            "*.json",
            "*.jsonl",
            "*.db",
            "*.sqlite*",
            "*.log",
            "*.pem",
            "*.key",
            ".env*",
        )
    )
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return [
        node,
        str(entry),
        "--settings",
        str(policy_path),
        "--",
        sys.executable,
        "-m",
        worker_module,
        "--worker",
    ]
