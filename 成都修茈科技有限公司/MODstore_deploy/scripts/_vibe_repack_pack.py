"""临时：用 library/<pack>/manifest.json 覆盖 catalog_data/files/<pack>-<ver>.xcemp 内的 manifest，
让 employee_runtime.load_employee_pack 看到我们的修改。可删。"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

from modstore_server.catalog_store import files_dir
from modstore_server.mod_scaffold_runner import modstore_library_path
from modstore_server.models import CatalogItem, get_session_factory


def main() -> None:
    pack_id = sys.argv[1] if len(sys.argv) > 1 else "doc-organizer"

    lib = modstore_library_path()
    pack_dir = lib / pack_id
    if not pack_dir.is_dir():
        print(f"library 不存在: {pack_dir}", file=sys.stderr)
        sys.exit(2)

    sf = get_session_factory()
    with sf() as s:
        row = s.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if not row:
            print(f"DB 无 CatalogItem: {pack_id}", file=sys.stderr)
            sys.exit(2)
        stored_filename = (row.stored_filename or "").strip()
        if not stored_filename:
            print(f"stored_filename 为空: {pack_id}", file=sys.stderr)
            sys.exit(2)

        xcemp = files_dir() / stored_filename
        if not xcemp.is_file():
            print(f"xcemp 不存在: {xcemp}", file=sys.stderr)
            sys.exit(2)

        # 把 library/pack_dir 下所有文件按相对路径塞回 zip，根目录前缀 = pack_id
        buf = io.BytesIO()
        included = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(pack_dir.rglob("*")):
                if not path.is_file():
                    continue
                # 跳过 __pycache__ 等运行时产物
                if any(part == "__pycache__" or part.endswith(".pyc") for part in path.parts):
                    continue
                rel = path.relative_to(pack_dir).as_posix()
                arcname = f"{pack_id}/{rel}"
                zf.write(path, arcname)
                included += 1
        raw = buf.getvalue()

        sha = hashlib.sha256(raw).hexdigest()
        xcemp.write_bytes(raw)
        row.sha256 = sha
        s.commit()
        print(f"OK · 重打包 {xcemp.name}  size={len(raw)}  sha256={sha[:16]}  files={included}")


if __name__ == "__main__":
    main()
