#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""通用 mod 打包脚本：将任意 mod 目录打包为 .xcmod / .xcemp。

进化状态闭环（2026-07-20）：系统自己打包上架 MODstore 的「打包」环节。

用法：
    python scripts/build_mod.py --mod-id employee-interview-assistant
    python scripts/build_mod.py --src FHD/mods/_employees/employee-interview-assistant
    python scripts/build_mod.py --mod-id new-employee --out dist/employee_packs --sign

输出：
    dist/employee_packs/<mod_id>-<version>.xcmod  (artifact=mod)
    dist/employee_packs/<mod_id>-<version>.xcemp  (artifact=employee_pack)
    dist/employee_packs/<mod_id>-<version>.meta.json  (含 sha256、size、build_at)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_src(mod_id: str | None, src: Path | None) -> Path:
    """解析 mod 源目录。优先 src，其次按 mod_id 在标准位置查找。"""
    if src:
        if not src.is_dir():
            raise SystemExit(f"--src 路径不存在或非目录：{src}")
        return src.resolve()
    if not mod_id:
        raise SystemExit("必须提供 --mod-id 或 --src")
    candidates = [
        REPO_ROOT / "mods" / "_employees" / mod_id,
        REPO_ROOT / "mods" / mod_id,
    ]
    for c in candidates:
        if c.is_dir():
            return c.resolve()
    raise SystemExit(f"未找到 mod 目录：{mod_id}（已检查 {[str(c) for c in candidates]}")


def _load_manifest(src: Path) -> dict:
    mf = src / "manifest.json"
    if not mf.is_file():
        raise SystemExit(f"缺少 manifest.json：{mf}")
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"manifest.json 解析失败：{exc}") from exc


def _validate_manifest(manifest: dict) -> list[str]:
    errs: list[str] = []
    for k in ("id", "name", "version"):
        if not str(manifest.get(k) or "").strip():
            errs.append(f"manifest.{k} 缺失")
    if str(manifest.get("artifact") or "mod").strip() not in ("employee_pack", "mod"):
        errs.append("manifest.artifact 应为 employee_pack 或 mod")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(manifest.get("id") or "")):
        errs.append("manifest.id 只能包含字母、数字、点、下划线和连字符")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", str(manifest.get("version") or "")):
        errs.append("manifest.version 格式无效")
    return errs


def _exclude_path(rel: str) -> bool:
    """打包排除规则（避免泄露敏感文件）。"""
    parts = rel.replace("\\", "/").split("/")
    if "__pycache__" in parts:
        return True
    if any(p.endswith(".pyc") for p in parts):
        return True
    if ".git" in parts:
        return True
    if "_local_secrets" in parts:
        return True
    if any(p.startswith(".env") for p in parts):
        return True
    if any(p.endswith(".key") or p.endswith(".pem") for p in parts):
        return True
    return False


def _write_reproducible_file(zf: zipfile.ZipFile, full: Path, rel: str) -> None:
    """Write one file without host mtime, uid, umask, or walk-order drift."""

    executable = bool(full.stat().st_mode & 0o111)
    mode = 0o755 if executable else 0o644
    info = zipfile.ZipInfo(rel, date_time=_ZIP_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16
    zf.writestr(info, full.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_xcemp(src: Path, out_dir: Path, *, sign: bool = False) -> tuple[Path, dict]:
    manifest = _load_manifest(src)
    errs = _validate_manifest(manifest)
    if errs:
        raise SystemExit(f"manifest 校验失败：{errs}")

    mod_id = str(manifest.get("id") or src.name)
    version = str(manifest.get("version") or "1.0.0")
    artifact = str(manifest.get("artifact") or "mod").strip()

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_version = version.replace("/", "_")
    suffix = ".xcemp" if artifact == "employee_pack" else ".xcmod"
    out_path = out_dir / f"{mod_id}-{safe_version}{suffix}"

    written: list[str] = []
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src):
            dirs.sort()
            for name in sorted(files):
                full = Path(root) / name
                rel = full.relative_to(src).as_posix()
                if _exclude_path(rel):
                    continue
                _write_reproducible_file(zf, full, rel)
                written.append(rel)

    # 计算 sha256
    sha = hashlib.sha256()
    size = 0
    with out_path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha.update(chunk)
            size += len(chunk)
    sha256 = sha.hexdigest()

    meta = {
        "id": mod_id,
        "version": version,
        "artifact": artifact,
        "path": str(out_path),
        "sha256": sha256,
        "size": size,
        "build_at": _utc_now(),
        "files": written,
        "files_count": len(written),
        "sign": sign,
    }
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path, meta


def main() -> None:
    parser = argparse.ArgumentParser(description="通用 mod 打包脚本")
    parser.add_argument("--mod-id", help="mod id（在 FHD/mods/ 或 FHD/mods/_employees/ 下查找）")
    parser.add_argument("--src", type=Path, help="mod 源目录（覆盖 --mod-id）")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "dist" / "employee_packs",
        help="输出目录（默认 dist/employee_packs）",
    )
    parser.add_argument("--sign", action="store_true", help="预留签名标志位（暂未实现签名算法）")
    args = parser.parse_args()

    src = _resolve_src(args.mod_id, args.src)
    out_path, meta = build_xcemp(src, args.out, sign=args.sign)
    print(f"OK: {out_path}")
    print(f"   sha256: {meta['sha256']}")
    print(f"   size:   {meta['size']} bytes")
    print(f"   files:  {meta['files_count']}")


if __name__ == "__main__":
    main()
