# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.get("/my-store")
def api_my_store(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = (
            session.query(_facade().Purchase).filter(_facade().Purchase.user_id == user.id).count()
        )
        rows = (
            session.query(_facade().Purchase)
            .filter(_facade().Purchase.user_id == user.id)
            .order_by(_facade().Purchase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = []
        for p in rows:
            item = (
                session.query(_facade().CatalogItem)
                .filter(_facade().CatalogItem.id == p.catalog_id)
                .first()
            )
            if item:
                items.append(
                    {
                        "purchase_id": p.id,
                        "catalog_id": item.id,
                        "pkg_id": item.pkg_id,
                        "version": item.version,
                        "name": item.name,
                        "artifact": item.artifact or "mod",
                        "price_paid": p.amount,
                        "purchased_at": p.created_at.isoformat() if p.created_at else "",
                    }
                )
        return {"items": items, "total": total}


def _catalog_files_dir() -> _facade().Path:
    """市场文件存储目录。"""
    d = _facade().Path(__file__).resolve().parent / "market_files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_chunks_dir() -> _facade().Path:
    """分块上传临时目录。"""
    d = _facade().Path(__file__).resolve().parent / "upload_chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d
