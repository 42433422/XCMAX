"""临时：直接对比 manifest root 与 MODSTORE_TENANT_WORKSPACE_ROOT 的 unicode codepoints。"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

from modstore_server.catalog_store import files_dir


def codepoints(s: str) -> str:
    return " ".join(f"U+{ord(c):04X}({c!r})" for c in s)


def main() -> None:
    ws_env = os.environ.get("MODSTORE_TENANT_WORKSPACE_ROOT", "")
    print("[ws_env raw      ]", ws_env, file=sys.stderr)
    print("[ws_env codepoints]", codepoints(ws_env), file=sys.stderr)
    ws_resolved = Path(ws_env).resolve() if ws_env else None
    print("[ws resolved     ]", ws_resolved, file=sys.stderr)
    if ws_resolved:
        print("[ws resolved cp  ]", codepoints(str(ws_resolved)), file=sys.stderr)

    xcemp = files_dir() / "doc-organizer-1.0.0.xcemp"
    with zipfile.ZipFile(xcemp, "r") as zf:
        m = json.loads(zf.read("doc-organizer/manifest.json").decode("utf-8"))
    root = m["employee_config_v2"]["actions"]["vibe_edit"]["root"]
    print("[manifest raw    ]", root, file=sys.stderr)
    print("[manifest cp     ]", codepoints(root), file=sys.stderr)
    target = Path(root).resolve()
    print("[target resolved ]", target, file=sys.stderr)
    print("[target cp       ]", codepoints(str(target)), file=sys.stderr)
    if ws_resolved:
        try:
            rel = target.relative_to(ws_resolved)
            print("[OK rel          ]", rel, file=sys.stderr)
        except ValueError as e:
            print("[FAIL relative_to]", e, file=sys.stderr)
        # 看磁盘真实大小写形式
        try:
            os_ws = os.path.realpath(str(ws_resolved))
            os_target = os.path.realpath(str(target))
            print("[realpath ws    ]", codepoints(os_ws), file=sys.stderr)
            print("[realpath target]", codepoints(os_target), file=sys.stderr)
        except OSError as e:
            print("[realpath err   ]", e, file=sys.stderr)


if __name__ == "__main__":
    main()
