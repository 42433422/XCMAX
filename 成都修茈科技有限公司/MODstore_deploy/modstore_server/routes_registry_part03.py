# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.routes_registry")


def _maybe_mount_dev_docs(app: _facade().FastAPI) -> None:
    docs_root = _facade().Path(__file__).resolve().parent.parent / "docs"
    if not docs_root.is_dir():
        return
    app.mount("/dev-docs", _facade().StaticFiles(directory=str(docs_root)), name="dev-docs")


def _maybe_mount_ui(app: _facade().FastAPI) -> None:
    root = _facade().Path(__file__).resolve().parent.parent
    dist = root / "web" / "dist"
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", _facade().StaticFiles(directory=str(assets)), name="ui-assets")
    index_file = dist / "index.html"

    @app.get("/")
    def ui_root():
        if index_file.is_file():
            return _facade().FileResponse(index_file)
        raise _facade().HTTPException(404)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if (
            full_path.startswith("api")
            or full_path.startswith("v1")
            or full_path.startswith("docs")
            or full_path.startswith("dev-docs")
            or full_path.startswith("redoc")
            or full_path.startswith("market")
            or (full_path == "openapi.json")
        ):
            raise _facade().HTTPException(404)
        if index_file.is_file():
            return _facade().FileResponse(index_file)
        raise _facade().HTTPException(404)


def register_all_routes(app: _facade().FastAPI) -> None:
    from modstore_server.api.market_routes import router as market_router
    from modstore_server.api.payment_routes import router as payment_router

    app.include_router(market_router)
    app.include_router(payment_router)
    from modstore_server.api.catalog_public_routes import router as catalog_public_router
    from modstore_server.mod_sync_catalog_api import router as mod_sync_catalog_router

    app.include_router(catalog_public_router)
    app.include_router(mod_sync_catalog_router)
    app.include_router(_facade().api_router)
    for _m in _facade()._OPTIONAL_MODULES:
        _facade()._include_optional(app, _m)
    _facade()._maybe_mount_dev_docs(app)
    _facade()._maybe_mount_ui(app)
