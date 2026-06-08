from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from modman.manifest_util import (
    folder_name_must_match_id,
    read_manifest,
    validate_manifest_dict,
)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_library() -> Path:
    env = __import__("os").environ.get("MODMAN_LIBRARY", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (project_root() / "library").resolve()


def default_xcagi_root() -> Optional[Path]:
    import os

    for key in ("XCAGI_ROOT", "MODMAN_XCAGI_ROOT"):
        v = os.environ.get(key, "").strip()
        if v:
            p = Path(v).expanduser().resolve()
            if p.is_dir():
                return p
    sibling = project_root().parent / "XCAGI"
    if sibling.is_dir():
        return sibling.resolve()
    return None


def iter_mod_dirs(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "manifest.json").is_file():
            yield child


def _manifest_frontend(data: dict) -> Optional[Dict[str, Any]]:
    fe = data.get("frontend")
    return fe if isinstance(fe, dict) else None


def _pick_manifest_str(data: dict, *keys: str) -> str:
    fe = _manifest_frontend(data)
    for src in (data, fe):
        if not isinstance(src, dict):
            continue
        for k in keys:
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _library_blurb_from_manifest(data: dict) -> str:
    return _pick_manifest_str(data, "library_blurb", "libraryBlurb")


def _mod_updated_at_iso(mod_dir: Path, data: dict) -> str:
    for key in ("updated_at", "updatedAt", "modified_at", "modifiedAt"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    try:
        mtime = (mod_dir / "manifest.json").stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _usage_scene_from_manifest(data: dict) -> str:
    routes = data.get("routes") or data.get("api_routes")
    if isinstance(routes, list) and routes:
        first = routes[0]
        if isinstance(first, dict):
            path = str(first.get("path") or first.get("url") or "").strip()
            if path:
                return f"HTTP {path}"
        elif isinstance(first, str) and first.strip():
            return f"路由 {first.strip()}"
    wf = data.get("workflow_employees")
    if isinstance(wf, list):
        for item in wf:
            if not isinstance(item, dict):
                continue
            ps = item.get("panel_summary") or item.get("label")
            if isinstance(ps, str) and ps.strip():
                text = ps.strip().replace("\n", " ")
                return text[:96] + ("…" if len(text) > 96 else "")
    skills = data.get("skills")
    if isinstance(skills, list) and skills:
        names: List[str] = []
        for sk in skills[:3]:
            if isinstance(sk, dict):
                n = str(sk.get("name") or sk.get("id") or "").strip()
                if n:
                    names.append(n)
            elif isinstance(sk, str) and sk.strip():
                names.append(sk.strip())
        if names:
            return "技能：" + "、".join(names)
    desc = str(data.get("description") or "").strip().replace("\n", " ")
    if desc:
        return desc[:96] + ("…" if len(desc) > 96 else "")
    return ""


def _mod_list_enrichment(mod_dir: Path, data: dict) -> dict:
    industry = data.get("industry")
    wf = data.get("workflow_employees")
    wf_clean: List[dict] = []
    if isinstance(wf, list):
        wf_clean = [x for x in wf if isinstance(x, dict)]
    desc = str(data.get("description") or "").strip()
    blurb = _library_blurb_from_manifest(data)
    artifact_raw = data.get("artifact") or data.get("kind") or "mod"
    artifact = artifact_raw.strip().lower() if isinstance(artifact_raw, str) else "mod"
    return {
        "description": desc,
        "library_blurb": blurb,
        "artifact": artifact,
        "industry": industry,
        "industry_id": _pick_manifest_str(data, "industry_id", "industryId") or None,
        "workflow_employees": wf_clean or None,
        "updated_at": _mod_updated_at_iso(mod_dir, data),
        "usage_scene": _usage_scene_from_manifest(data),
    }


def list_mods(library: Path) -> List[dict]:
    rows: List[dict] = []
    for d in iter_mod_dirs(library):
        data, err = read_manifest(d)
        if err or not data:
            rows.append(
                {
                    "path": str(d),
                    "id": d.name,
                    "ok": False,
                    "error": err or "empty",
                }
            )
            continue
        ve = validate_manifest_dict(data)
        fn = folder_name_must_match_id(d, data)
        if fn:
            ve.append(fn)
        row = {
            "path": str(d),
            "id": data.get("id", d.name),
            "name": data.get("name", ""),
            "version": data.get("version", ""),
            "primary": bool(data.get("primary")),
            "ok": len(ve) == 0,
            "warnings": ve,
        }
        row.update(_mod_list_enrichment(d, data))
        rows.append(row)
    return rows


def _copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, dirs_exist_ok=False)


def _manifest_artifact_is_employee_pack(data: dict) -> bool:
    raw = data.get("artifact") or data.get("kind") or ""
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() == "employee_pack"


def ingest_mod(src: Path, library: Path) -> Path:
    src = src.resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"源不是目录: {src}")
    data, err = read_manifest(src)
    if err or not data:
        raise ValueError(err or "manifest 无效")
    ve = validate_manifest_dict(data)
    mid = (data.get("id") or "").strip()
    if not mid:
        raise ValueError("manifest 缺少 id")
    if ve:
        raise ValueError("manifest 校验未通过: " + "; ".join(ve))
    dest = library / mid
    library.mkdir(parents=True, exist_ok=True)
    _copytree(src, dest)
    return dest


def deploy_to_xcagi(
    mod_ids: Optional[List[str]],
    library: Path,
    xcagi_root: Path,
    *,
    replace: bool = True,
) -> List[str]:
    mods_dir = xcagi_root / "mods"
    if not mods_dir.is_dir():
        mods_dir.mkdir(parents=True, exist_ok=True)
    done: List[str] = []
    candidates = list_mods(library)
    id_set = set(mod_ids) if mod_ids else None
    for row in candidates:
        mid = row["id"]
        if id_set is not None and mid not in id_set:
            continue
        if not row.get("ok"):
            raise ValueError(f"Mod {mid} 校验未通过，跳过部署: {row.get('warnings')}")
        src = Path(row["path"])
        mf, merr = read_manifest(src)
        if merr or not mf:
            raise ValueError(f"Mod {mid}: 无法读取 manifest: {merr or 'empty'}")
        if _manifest_artifact_is_employee_pack(mf):
            emp_root = mods_dir / "_employees"
            emp_root.mkdir(parents=True, exist_ok=True)
            dst = emp_root / mid
        else:
            dst = mods_dir / mid
        if dst.exists():
            if not replace:
                raise FileExistsError(f"目标已存在: {dst}")
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        done.append(mid)
    return done


def pull_from_xcagi(
    mod_ids: Optional[List[str]],
    library: Path,
    xcagi_root: Path,
    *,
    replace: bool = True,
) -> List[str]:
    mods_dir = xcagi_root / "mods"
    if not mods_dir.is_dir():
        raise FileNotFoundError(f"XCAGI mods 目录不存在: {mods_dir}")
    done: List[str] = []

    def _pull_one(child: Path) -> None:
        if not child.is_dir():
            return
        if mod_ids and child.name not in mod_ids:
            return
        if not (child / "manifest.json").is_file():
            return
        dest = library / child.name
        library.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if not replace:
                raise FileExistsError(f"库中已存在: {dest}")
            shutil.rmtree(dest)
        shutil.copytree(child, dest)
        done.append(child.name)

    for child in sorted(mods_dir.iterdir()):
        if child.name == "_employees":
            continue
        _pull_one(child)

    emp_dir = mods_dir / "_employees"
    if emp_dir.is_dir():
        for child in sorted(emp_dir.iterdir()):
            _pull_one(child)

    return done


def export_zip(mod_dir: Path, zip_path: Path) -> None:
    mod_dir = mod_dir.resolve()
    if not (mod_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"不是有效 Mod 目录: {mod_dir}")
    zip_path = zip_path.resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in mod_dir.rglob("*"):
            if f.is_file():
                arc = f.relative_to(mod_dir)
                zf.write(f, arc.as_posix())


def build_mod_zip_bytes(mod_dir: Path) -> io.BytesIO:
    """Zip a Mod directory into an in-memory buffer (for ``StreamingResponse``)."""

    mod_dir = mod_dir.resolve()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in mod_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(mod_dir).as_posix())
    buf.seek(0)
    return buf


def import_zip(zip_path: Path, library: Path, *, replace: bool = True) -> Path:
    zip_path = zip_path.resolve()
    library.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("空 zip")
        top_levels = {n.split("/")[0].strip() for n in names if n.strip()}
        if len(top_levels) != 1:
            raise ValueError(
                "zip 顶层应只有一个文件夹（例如 my-mod/manifest.json），实际: "
                + ", ".join(sorted(top_levels)[:10])
            )
        root_name = next(iter(top_levels))
        extract_to = library / root_name
        if extract_to.exists():
            if not replace:
                raise FileExistsError(str(extract_to))
            shutil.rmtree(extract_to)
        zf.extractall(library)
    mod_dir = library / root_name
    data, err = read_manifest(mod_dir)
    if err or not data:
        shutil.rmtree(mod_dir, ignore_errors=True)
        raise ValueError(err or "解压后 manifest 无效")
    mid = (data.get("id") or "").strip()
    if mid != mod_dir.name:
        shutil.rmtree(mod_dir, ignore_errors=True)
        raise ValueError(f"zip 内文件夹名 {mod_dir.name!r} 须与 manifest.id {mid!r} 一致")
    ve = validate_manifest_dict(data)
    if ve:
        raise ValueError("manifest: " + "; ".join(ve))
    return mod_dir


def write_registry_note(library: Path, note: dict) -> None:
    p = library / "_registry.json"
    p.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_mod(library: Path, mod_id: str) -> None:
    if not mod_id or "/" in mod_id or "\\" in mod_id or mod_id in (".", ".."):
        raise ValueError("非法 mod id")
    lib = library.resolve()
    p = (library / mod_id).resolve()
    if p.parent.resolve() != lib:
        raise ValueError("非法路径")
    if not p.is_dir():
        raise FileNotFoundError(mod_id)
    shutil.rmtree(p)


def find_mod_dir_by_manifest_id(library: Path, mod_id: str) -> Path:
    """
    在 library 下定位 manifest.id == mod_id 的包目录。
    目录名通常与 id 一致；若历史数据不一致，仍能通过 manifest 命中磁盘目录。
    """
    if not mod_id or "/" in mod_id or "\\" in mod_id or mod_id in (".", ".."):
        raise ValueError("非法 mod id")
    target = mod_id.strip()
    if not target:
        raise ValueError("非法 mod id")
    lib = library.resolve()
    for d in iter_mod_dirs(library):
        data, err = read_manifest(d)
        if err or not data:
            continue
        mid = (data.get("id") or "").strip()
        if mid == target:
            p = d.resolve()
            if p.parent.resolve() == lib:
                return p
    p = (library / target).resolve()
    if p.is_dir() and p.parent.resolve() == lib:
        return p
    raise FileNotFoundError(target)


def remove_mod_by_manifest_id(library: Path, mod_id: str) -> None:
    """按 manifest id 删除包目录（解析真实文件夹名，与 user_mod 中的 mod_id 一致）。"""
    p = find_mod_dir_by_manifest_id(library, mod_id)
    shutil.rmtree(p)


def list_mod_relative_files(mod_dir: Path, *, max_files: int = 400) -> List[str]:
    mod_dir = mod_dir.resolve()
    out: List[str] = []
    for f in sorted(mod_dir.rglob("*")):
        if not f.is_file():
            continue
        if any(part.startswith(".") for part in f.relative_to(mod_dir).parts):
            continue
        out.append(f.relative_to(mod_dir).as_posix())
        if len(out) >= max_files:
            break
    return out
