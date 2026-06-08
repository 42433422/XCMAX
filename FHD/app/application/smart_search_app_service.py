"""智能搜索 V0 应用服务（M3-W2）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

Scope = Literal["products", "customers", "excel", "all"]


class SmartSearchApplicationService:
    def search_products(self, keyword: str, *, per_page: int = 20) -> dict[str, Any]:
        from app.application.product_app_service import get_product_application_service

        return get_product_application_service().get_products(
            keyword=keyword or None,
            page=1,
            per_page=per_page,
        )

    def search_customers(self, keyword: str, *, per_page: int = 20) -> dict[str, Any]:
        from app.application.customer_app_service import get_customer_app_service

        return get_customer_app_service().get_all(
            keyword=keyword or None,
            page=1,
            per_page=per_page,
        )

    def search_excel_vector(self, keyword: str, *, top_k: int = 5) -> dict[str, Any]:
        from app.application.excel_vector_app_service import get_excel_vector_search_app_service

        svc = get_excel_vector_search_app_service()
        indexes = svc.list_indexes()
        index_rows = (indexes.get("indexes") or []) if isinstance(indexes, dict) else []
        if not index_rows:
            return {"success": True, "query": keyword, "hits": [], "index_id": None}
        first = index_rows[0]
        index_id = str(first.get("index_id") or first.get("id") or "")
        if not index_id:
            return {"success": True, "query": keyword, "hits": [], "index_id": None}
        try:
            return svc.query(index_id=index_id, query_text=keyword, top_k=top_k)
        except Exception as exc:
            logger.exception("search_excel_vector")
            return {"success": False, "message": str(exc), "hits": [], "index_id": index_id}

    def search(
        self,
        keyword: str,
        *,
        scope: Scope = "products",
        per_page: int = 20,
    ) -> dict[str, Any]:
        q = (keyword or "").strip()
        out: dict[str, Any] = {
            "success": True,
            "query": q,
            "scope": scope,
            "results": {},
        }

        if scope in ("products", "all"):
            try:
                out["results"]["products"] = self.search_products(q, per_page=per_page)
            except Exception as exc:
                logger.exception("smart_search products")
                out["results"]["products"] = {"success": False, "message": str(exc), "data": []}

        if scope in ("customers", "all"):
            try:
                out["results"]["customers"] = self.search_customers(q, per_page=per_page)
            except Exception as exc:
                logger.exception("smart_search customers")
                out["results"]["customers"] = {"success": False, "message": str(exc), "data": []}

        if scope in ("excel", "all"):
            try:
                out["results"]["excel_vector"] = self.search_excel_vector(q, top_k=5)
            except Exception as exc:
                logger.exception("smart_search excel")
                out["results"]["excel_vector"] = {"success": False, "message": str(exc), "hits": []}

        blocks = out["results"].values()
        any_ok = any(isinstance(block, dict) and block.get("success") for block in blocks)
        out["success"] = any_ok if out["results"] else True
        return out


_smart_search_app_service: SmartSearchApplicationService | None = None


def get_smart_search_app_service() -> SmartSearchApplicationService:
    global _smart_search_app_service
    if _smart_search_app_service is None:
        _smart_search_app_service = SmartSearchApplicationService()
    return _smart_search_app_service
