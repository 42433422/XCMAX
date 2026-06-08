"""临时：用 Python 子进程方式启动 uvicorn，确保 CJK 环境变量不被 PowerShell 重编码。可删。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    deploy_root = Path(__file__).resolve().parents[1]
    repo_root = deploy_root.parent

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ["MODSTORE_RUNTIME_DIR"] = str(deploy_root / "var" / "runtime")
    # 用 absolute path of the repo root so vibe_edit's root 校验能通过
    os.environ["MODSTORE_TENANT_WORKSPACE_ROOT"] = str(repo_root)
    os.environ.setdefault("VIBE_CODING_STORE_DIR", str(deploy_root / "var" / "vibe_coding"))

    # 打印 sanity-check
    print("[uvicorn-launcher] MODSTORE_TENANT_WORKSPACE_ROOT =", repr(os.environ["MODSTORE_TENANT_WORKSPACE_ROOT"]), flush=True)
    print("[uvicorn-launcher] VIBE_CODING_STORE_DIR        =", repr(os.environ["VIBE_CODING_STORE_DIR"]), flush=True)

    import uvicorn
    uvicorn.run(
        "modstore_server.app:app",
        host="127.0.0.1",
        port=8765,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
