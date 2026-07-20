#!/usr/bin/env python3
"""Force-trigger the MODstore self-maintenance loop for P1 test.

Loads env snapshot from /Users/a4243342/Library/Application Support/XCMAX/modstore-daily.env
plus runtime overrides, then invokes run_self_maintenance_loop(force=True).
"""
import os
import sys
from pathlib import Path


def load_env_snapshot(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            value = value[1:-1]
        if key:
            os.environ[key] = value


def main() -> int:
    runtime_state_root = Path("/Users/a4243342/Library/Application Support/XCMAX/modstore-daily")
    runtime_root = Path("/Users/a4243342/XCMAX-runtime/modstore-daily")
    deploy_root = runtime_root / "MODstore_deploy"
    fhd_root = runtime_root / "FHD"

    load_env_snapshot(Path("/Users/a4243342/Library/Application Support/XCMAX/modstore-daily.env"))

    # Runtime overrides
    os.environ["MODSTORE_DAILY_FOREGROUND"] = "1"
    os.environ["MODSTORE_DAILY_ROLE"] = "scheduler"
    os.environ["MODSTORE_CONTROL_PORT"] = "8788"
    os.environ["MODSTORE_PORT"] = "8788"
    os.environ["MODSTORE_DAILY_FHD_ROOT"] = str(fhd_root)
    os.environ["MODSTORE_DAILY_XCMAX_ROOT"] = str(runtime_root)
    os.environ["MODSTORE_RUNTIME_ROOT"] = str(runtime_root)
    os.environ["MODSTORE_RUNTIME_STATE_ROOT"] = str(runtime_state_root)
    os.environ["MODSTORE_RUNTIME_DB_PATH"] = str(runtime_state_root / "modstore.db")
    os.environ["MODSTORE_RUNTIME_DIR"] = str(runtime_state_root / "runtime")
    os.environ["MODSTORE_DEPLOY_ROOT"] = str(deploy_root)
    os.environ["MODSTORE_REPO_ROOT"] = str(deploy_root)
    # IMPORTANT: XCMAX_MONOREPO_ROOT must point to Desktop/XCMAX (with full
    # FHD/app/domain/autonomy/), NOT runtime_root which has a stripped FHD.
    os.environ["XCMAX_MONOREPO_ROOT"] = "/Users/a4243342/Desktop/XCMAX"
    os.environ["XCAGI_FHD_ROOT"] = str(fhd_root)
    os.environ["MODSTORE_DB_PATH"] = str(runtime_state_root / "modstore.db")
    os.environ["DATABASE_URL"] = f"sqlite:////{runtime_state_root / 'modstore.db'}"
    os.environ["PYTHONPATH"] = (
        f"{deploy_root}:{runtime_root / 'packages' / 'xcagi_common'}"
    )
    os.environ["MODSTORE_RUN_BACKGROUND_JOBS"] = "0"
    os.environ["MODSTORE_LOCAL_AUTOMATION"] = "1"
    os.environ["MODSTORE_INTERNAL_API_BASE"] = "http://127.0.0.1:8788"
    os.environ["XCAGI_MARKET_BASE_URL"] = "http://127.0.0.1:8788"
    os.environ["MODSTORE_LOCAL_BASE_URL"] = "http://127.0.0.1:8788"
    os.environ["MODSTORE_DIGEST_BASE_URL"] = "http://127.0.0.1:8788"
    os.environ["MODSTORE_ALL_HANDS_BASE_URL"] = "http://127.0.0.1:8788"
    os.environ["MODSTORE_EVENT_STREAM_ENABLED"] = "0"
    for k in (
        "REDIS_URL",
        "REDIS_PORT",
        "MODSTORE_REDIS_URL",
        "MODSTORE_EVENT_STREAM_URL",
        "CACHE_REDIS_URL",
        "XCAGI_REDIS_URL",
        "MODSTORE_VECTOR_REDIS_URL",
    ):
        os.environ.pop(k, None)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"

    os.chdir(str(deploy_root))
    sys.path.insert(0, str(deploy_root))
    sys.path.insert(0, str(runtime_root / "packages" / "xcagi_common"))

    from modstore_server.self_maintenance_loop_runner import (
        run_self_maintenance_loop,
        _loop_startup_preflight,
    )

    preflight = _loop_startup_preflight()
    print(f"[trigger] preflight: {preflight}", flush=True)
    if not preflight.get("ok"):
        print(f"[trigger] FAIL-FAST: {preflight}", flush=True)
        return 2

    print(
        f"[trigger] invoking run_self_maintenance_loop force=True "
        f"triggered_by=manual_p1_test",
        flush=True,
    )
    result = run_self_maintenance_loop(
        triggered_by="manual_p1_test",
        force=True,
        reason="P1_first_closed_loop_test",
    )
    print("[trigger] result:", flush=True)
    print(result, flush=True)
    return 0 if result.get("status", "").startswith("completed") else 1


if __name__ == "__main__":
    sys.exit(main())
