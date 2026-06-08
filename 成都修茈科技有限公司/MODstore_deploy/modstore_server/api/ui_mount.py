"""Optional static mounts: developer docs and built web UI (SPA fallback)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def maybe_mount_dev_docs(app: FastAPI) -> None:
    docs_root = Path(__file__).resolve().parents[2] / "docs"
    if not docs_root.is_dir():
        return
    app.mount("/dev-docs", StaticFiles(directory=str(docs_root)), name="dev-docs")


def maybe_mount_ui(app: FastAPI) -> None:
    root = Path(__file__).resolve().parents[2]
    dist = root / "web" / "dist"
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="ui-assets")

    index_file = dist / "index.html"

    @app.get("/")
    def ui_root():
        if index_file.is_file():
            return FileResponse(index_file)
        raise HTTPException(404)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if (
            full_path.startswith("api")
            or full_path.startswith("v1")
            or full_path.startswith("docs")
            or full_path.startswith("dev-docs")
            or full_path.startswith("redoc")
            or full_path.startswith("market")
            or full_path == "openapi.json"
        ):
            raise HTTPException(404)
        if index_file.is_file():
            return FileResponse(index_file)
        raise HTTPException(404)
