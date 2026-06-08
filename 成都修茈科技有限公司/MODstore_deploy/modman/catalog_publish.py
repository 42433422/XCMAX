"""将本地 .xcmod / .xcemp 发布到 Catalog 服务（POST /v1/packages）。"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, cast

from modman.artifact_constants import normalize_artifact


def _read_manifest_from_zip(zip_path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if "manifest.json" in names:
            blob = json.loads(zf.read("manifest.json").decode("utf-8"))
            if not isinstance(blob, dict):
                raise ValueError("manifest.json 根类型必须是对象")
            return cast(Dict[str, Any], blob)
        cands = [n for n in names if n.endswith("/manifest.json") and n.count("/") == 1]
        if not cands:
            raise ValueError("zip 内无 manifest.json")
        blob = json.loads(zf.read(sorted(cands)[0]).decode("utf-8"))
        if not isinstance(blob, dict):
            raise ValueError("manifest.json 根类型必须是对象")
        return cast(Dict[str, Any], blob)


def build_record(zip_path: Path) -> Dict[str, Any]:
    m = _read_manifest_from_zip(zip_path)
    pid = str(m.get("id") or "").strip()
    ver = str(m.get("version") or "").strip()
    if not pid or not ver:
        raise ValueError("manifest 缺少 id 或 version")
    return {
        "id": pid,
        "version": ver,
        "name": str(m.get("name") or pid),
        "author": str(m.get("author") or ""),
        "description": str(m.get("description") or ""),
        "artifact": normalize_artifact(m),
        "tags": m.get("tags") if isinstance(m.get("tags"), list) else [],
        "commerce": {"mode": "free", "product_id": None, "sku": None},
        "license": {"type": "none", "verify_url": None},
    }


def publish_zip(zip_path: Path, catalog_url: str, token: str) -> tuple[int, str]:
    try:
        import httpx
    except ImportError:
        return 1, "需要安装 httpx：pip install httpx"

    record = build_record(zip_path)
    base = catalog_url.rstrip("/")
    url = f"{base}/v1/packages"
    meta = json.dumps(record, ensure_ascii=False)
    with zip_path.open("rb") as fh:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"metadata": meta},
            files={"file": (zip_path.name, fh, "application/zip")},
            timeout=120.0,
        )
    if r.status_code >= 400:
        return 1, f"HTTP {r.status_code}: {r.text[:2000]}"
    return 0, r.text


def main_publish(zip_path: str, catalog_url: str, token: str) -> int:
    p = Path(zip_path).expanduser().resolve()
    if not p.is_file():
        print(f"文件不存在: {p}", file=sys.stderr)
        return 1
    try:
        code, msg = publish_zip(p, catalog_url, token)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1
    if code != 0:
        print(msg, file=sys.stderr)
        return code
    print(msg)
    return 0
