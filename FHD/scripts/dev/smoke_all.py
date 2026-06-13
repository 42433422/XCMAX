# -*- coding: utf-8 -*-
"""聚合冒烟：一次跑完 Mod 边界 / werkzeug shim / FastAPI 启动 / GET 路由扫描。

用法：

    $env:PYTHONPATH = (Get-Location).Path
    python scripts/dev/smoke_all.py

任意一个 step 失败都会中断并以非零退出码结束；每个 step 的耗时与摘要写到 stdout。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _run_subprocess(label: str, argv: list[str]) -> int:
    _banner(label)
    t0 = time.time()
    proc = subprocess.run(argv, cwd=REPO_ROOT)
    dt = time.time() - t0
    print(f"[{label}] exit={proc.returncode}  elapsed={dt:.2f}s")
    return proc.returncode


def step_mod_boundary() -> int:
    return _run_subprocess(
        "Mod 边界 lint (scripts/dev/check_mod_import_boundaries.py)",
        [sys.executable, str(REPO_ROOT / "scripts/dev/check_mod_import_boundaries.py")],
    )


def step_layer_ratchet() -> int:
    return _run_subprocess(
        "分层债棘轮 (scripts/dev/check_layer_ratchet.py)",
        [sys.executable, str(REPO_ROOT / "scripts/dev/check_layer_ratchet.py")],
    )


def step_werkzeug_shim() -> int:
    return _run_subprocess(
        "werkzeug shim parity (scripts/dev/smoke_werkzeug_shim.py)",
        [sys.executable, str(REPO_ROOT / "scripts/dev/smoke_werkzeug_shim.py")],
    )


def step_fastapi_boot() -> int:
    _banner("FastAPI 整机启动（get_fastapi_app）")
    t0 = time.time()
    # 屏蔽路由注册日志让结果干净
    for name in (
        "app",
        "app.fastapi_app",
        "app.fastapi_routes",
        "app.middleware.error_handler",
        "app.neuro_bus.bus",
        "app.neuro_bus.integrations.fastapi_integration",
        "resources.config.intent_config",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        from app.fastapi_app import get_fastapi_app

        app = get_fastapi_app()
    except Exception as e:
        print(f"[FastAPI boot] FAILED: {type(e).__name__}: {e}")
        return 1
    dt = time.time() - t0
    print(f"[FastAPI boot] OK  routes={len(app.routes)}  elapsed={dt:.2f}s")
    return 0


def step_get_routes_smoke() -> int:
    return _run_subprocess(
        "参数自由 GET 路由扫描 (scripts/smoke_paramfree_get_routes.py)",
        [sys.executable, str(REPO_ROOT / "scripts/smoke_paramfree_get_routes.py")],
    )


def main() -> int:
    steps = (
        ("mod_boundary", step_mod_boundary),
        ("layer_ratchet", step_layer_ratchet),
        ("werkzeug_shim", step_werkzeug_shim),
        ("fastapi_boot", step_fastapi_boot),
        ("get_routes_smoke", step_get_routes_smoke),
    )
    results: list[tuple[str, int]] = []
    for name, fn in steps:
        rc = fn()
        results.append((name, rc))
        if rc != 0:
            print(f"\nABORT at step: {name} (exit={rc})")
            break

    _banner("SUMMARY")
    for name, rc in results:
        mark = "OK" if rc == 0 else "FAIL"
        print(f"  [{mark}]  {name}  (exit={rc})")

    if any(rc != 0 for _, rc in results) or len(results) != len(steps):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
