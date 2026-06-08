"""导出 modstore_server FastAPI app 的 OpenAPI 快照。

用途：

- 开发期：``python scripts/export_openapi.py`` → 写
  ``docs/contracts/openapi/modstore-server.json``；
- CI：把这个 JSON 与上次提交的版本做 diff，发现破坏性变化
  （字段删除、必填新增、状态码缺失等）。

设计要点：

- 只调用 ``app.openapi()``，不启动 uvicorn、不连数据库；
- 路由模块在 import 期间已自登记到 ``app``，无需额外 lifespan；
- ``--check`` 模式在文件已存在且与 spec 不一致时返回非 0，方便 CI 拦截
  "改了 API 但忘了刷文档" 的提交。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _build_paths() -> tuple[Path, Path, Path]:
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    out_dir = repo_root / "docs" / "contracts" / "openapi"
    out_path = out_dir / "modstore-server.json"
    return repo_root, out_dir, out_path


def _load_app() -> Any:
    repo_root, _, _ = _build_paths()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from modstore_server.app import app  # noqa: WPS433 (intentional local import)

    return app


def export(check_only: bool = False) -> int:
    _, out_dir, out_path = _build_paths()
    app = _load_app()
    spec = app.openapi()
    rendered = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = rendered.encode("utf-8")  # bytes 模式避免 Windows CRLF 转换让 CI 拿到假 diff
    if check_only and out_path.is_file():
        existing = out_path.read_bytes()
        if existing != payload:
            sys.stderr.write(
                f"OpenAPI snapshot is stale: {out_path}\n"
                "运行 `python scripts/export_openapi.py` 重新生成后再提交。\n"
            )
            return 1
        sys.stdout.write("OpenAPI snapshot is up to date.\n")
        return 0

    out_path.write_bytes(payload)
    sys.stdout.write(f"wrote {out_path} ({len(payload)} bytes)\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查，不写入；快照与当前 spec 不一致时返回非 0，适合 CI",
    )
    args = parser.parse_args()
    return export(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
