"""Build avatar-generation-employee.xcemp from this employee_pack directory."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACK_ID = "avatar-generation-employee"


def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    out = ROOT / f"{PACK_ID}.xcemp"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{PACK_ID}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        for path in sorted((ROOT / "backend").rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".py":
                continue
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, f"{PACK_ID}/{rel}")
        for name in ("README.md", "rule_spec.json", "asset_manifest.json"):
            path = ROOT / name
            if path.is_file():
                zf.write(path, f"{PACK_ID}/{name}")
    out.write_bytes(buf.getvalue())
    print(out)


if __name__ == "__main__":
    main()
