"""Library / XCAGI configuration routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from modman.fhd_shell_export import write_fhd_shell_mods_json
from modman.repo_config import (
    RepoConfig,
    resolved_library,
    resolved_xcagi,
    resolved_xcagi_backend_url,
)
from modstore_server.api.dto import ConfigDTO, ExportFhdShellDTO
from modstore_server.infrastructure import library_paths

router = APIRouter(tags=["config"])


@router.get("/api/config")
def get_config():
    cfg = library_paths.cfg()
    lib = resolved_library(cfg)
    xc = resolved_xcagi(cfg)
    st = library_paths.load_state()
    return {
        "library_root": str(lib),
        "xcagi_root": str(xc) if xc else "",
        "library_exists": lib.is_dir(),
        "xcagi_ok": bool(xc and (xc / "mods").is_dir()),
        "saved_library_root": cfg.library_root,
        "saved_xcagi_root": cfg.xcagi_root,
        "saved_xcagi_backend_url": cfg.xcagi_backend_url,
        "xcagi_backend_url": resolved_xcagi_backend_url(cfg),
        "state": {
            "last_sandbox_mods_root": st.get("last_sandbox_mods_root") or "",
            "last_sandbox_mod_id": st.get("last_sandbox_mod_id") or "",
            "focus_mod_id": st.get("focus_mod_id") or "",
        },
    }


@router.post("/api/export/fhd-shell-mods")
def api_export_fhd_shell_mods(body: ExportFhdShellDTO = Body(default_factory=ExportFhdShellDTO)):
    fhd = library_paths.fhd_repo_root()
    if not fhd.is_dir():
        raise HTTPException(500, "无法定位 FHD 仓库根目录（预期 MODstore 位于 FHD/MODstore）")
    raw = body.output_path or ""
    raw = raw.strip()
    if raw:
        target = Path(raw).expanduser().resolve()
    else:
        target = (fhd / "backend" / "shell" / "fhd_shell_mods.json").resolve()
    try:
        library_paths.assert_path_inside_fhd_repo(fhd, target)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    lib = library_paths.lib()
    n = write_fhd_shell_mods_json(lib, target)
    return {"ok": True, "path": str(target), "count": n}


@router.put("/api/config")
def put_config(body: ConfigDTO):
    lr = (body.library_root or "").strip()
    xr = (body.xcagi_root or "").strip()
    url = (body.xcagi_backend_url or "").strip()
    cfg = RepoConfig(
        library_root=str(Path(lr).expanduser().resolve()) if lr else "",
        xcagi_root=str(Path(xr).expanduser().resolve()) if xr else "",
        xcagi_backend_url=url,
    )
    library_paths.save_config(cfg)
    if cfg.library_root:
        Path(cfg.library_root).mkdir(parents=True, exist_ok=True)
    return get_config()
