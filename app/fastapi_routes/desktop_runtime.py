from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.desktop_runtime import ensure_desktop_dirs, is_desktop_mode
from app.desktop_runtime.model_downloader import ModelAsset, download_model, load_manifest

router = APIRouter(prefix="/api/desktop", tags=["desktop-runtime"])


class DownloadModelRequest(BaseModel):
    name: str
    version: str
    url: str
    sha256: str
    size: int | None = None


@router.get("/status")
def desktop_status():
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    return {
        "desktopMode": is_desktop_mode(),
        "dataDir": str(dirs["root"]),
        "database": str(dirs["data"] / "xcagi.db"),
        "modsDir": str(dirs["mods"]),
        "modelsDir": str(dirs["models"]),
        "webModeCompatible": True,
    }


@router.get("/models")
def list_models():
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    root = dirs["models"]
    models = []
    for path in root.glob("*/*"):
        if path.is_dir():
            models.append({"name": path.parent.name, "version": path.name, "path": str(path)})
    return {"models": models}


@router.post("/models/download")
def download_model_asset(request: DownloadModelRequest):
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="模型下载仅在桌面模式下可写入 userData")
    asset = ModelAsset(**request.model_dump())
    target = download_model(asset, data_dir=os.environ.get("XCAGI_DATA_DIR"))
    return {"ok": True, "path": str(target)}


@router.post("/models/install-manifest")
def install_manifest(path: str):
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="模型下载仅在桌面模式下可写入 userData")
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="manifest not found")
    targets = [
        str(target)
        for target in (
            download_model(asset, data_dir=os.environ.get("XCAGI_DATA_DIR"))
            for asset in load_manifest(manifest_path)
        )
    ]
    return {"ok": True, "files": targets}
