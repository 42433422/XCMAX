"""产品仓储：服务层 dict API 以 persistence 为 SSOT。

域实体版查询（``find_all`` 返回 ``Product`` 元组）见 ``DomainProductRepository``；
``SQLAlchemyProductRepository`` 与 ``products_service`` 一致，委托
``app.infrastructure.persistence.product_repository_impl``。
"""

from __future__ import annotations

from app.infrastructure.persistence.product_repository_impl import (
    SQLAlchemyProductRepository,
    TRIVIAL_MEASURE_UNITS,
)

__all__ = ["SQLAlchemyProductRepository", "TRIVIAL_MEASURE_UNITS", "DomainProductRepository"]


# 域测试与 NeuroBus 域层仍可使用（避免与 dict API 的 find_all 签名冲突）
from app.db.models import Product as ProductModel
from app.db.session import get_db
from app.domain.product.entities import Product
from app.infrastructure.mappers.product_mapper import product_to_domain, product_to_db
from app.infrastructure.repositories.product_repository import ProductRepository as DomainProductRepositoryBase


class DomainProductRepository(DomainProductRepositoryBase):
    """产品仓储 SQLAlchemy 实现（域 ``Product`` 实体）。"""

    def _to_domain(self, db_model: ProductModel) -> Product:
        return product_to_domain(db_model)

    def _to_db_model(self, product: Product) -> dict:
        return product_to_db(product)

    def save(self, product: Product) -> Product:
        from datetime import datetime

        with get_db() as db:
            if product.id:
                existing = db.query(ProductModel).filter(ProductModel.id == product.id).first()
                if existing:
                    for key, value in self._to_db_model(product).items():
                        setattr(existing, key, value)
                    existing.updated_at = datetime.now()
                    db.commit()
                    db.refresh(existing)
                    return self._to_domain(existing)

            db_model = ProductModel(**self._to_db_model(product))
            db.add(db_model)
            db.commit()
            db.refresh(db_model)
            return self._to_domain(db_model)

    def create(self, product: Product) -> Product:
        return self.save(product)

    def find_by_id(self, product_id: int) -> Product | None:
        with get_db() as db:
            model = db.query(ProductModel).filter(ProductModel.id == product_id).first()
            return self._to_domain(model) if model else None

    def find_all(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        import re
        from typing import Any

        with get_db() as db:
            offset = (page - 1) * per_page
            query = db.query(ProductModel)
            unit_name = kwargs.get("unit_name")
            if unit_name:
                query = query.filter(ProductModel.unit == unit_name)
            model_number = kwargs.get("model_number")
            if model_number:
                from sqlalchemy import or_

                pattern = f"%{str(model_number).strip()}%"
                query = query.filter(
                    or_(
                        ProductModel.model_number.like(pattern),
                        ProductModel.name.like(pattern),
                    )
                )
            keyword = kwargs.get("keyword")
            if keyword:
                from sqlalchemy import func, or_

                keyword_text = str(keyword).strip()
                u = func.coalesce(ProductModel.unit, "")
                n = func.coalesce(ProductModel.name, "")
                m = func.coalesce(ProductModel.model_number, "")
                s = func.coalesce(ProductModel.specification, "")
                concat_blob = u.op("||")(n).op("||")(m).op("||")(s)

                def _one_kw(kw: str) -> Any:
                    k = str(kw).strip()
                    if not k:
                        return None
                    tok = k.upper().replace("-", "").replace(" ", "")
                    nm = func.upper(
                        func.replace(
                            func.replace(func.coalesce(ProductModel.model_number, ""), "-", ""),
                            " ",
                            "",
                        )
                    )
                    return or_(
                        ProductModel.unit.like(f"%{k}%"),
                        ProductModel.name.like(f"%{k}%"),
                        ProductModel.model_number.like(f"%{k}%"),
                        ProductModel.specification.like(f"%{k}%"),
                        nm.like(f"%{tok}%"),
                        concat_blob.like(f"%{k}%"),
                    )

                segments = re.findall(r"[\u4e00-\u9fff]+|[0-9]+|[A-Za-z]+", keyword_text)
                segments = [p for p in segments if p.strip()]
                if len(segments) > 1:
                    for seg in segments:
                        filt = _one_kw(seg)
                        if filt is not None:
                            query = query.filter(filt)
                else:
                    kw_use = segments[0] if segments else keyword_text
                    filt = _one_kw(kw_use if kw_use else keyword_text)
                    if filt is not None:
                        query = query.filter(filt)

            total = query.count()
            models = query.order_by(ProductModel.id.desc()).limit(per_page).offset(offset).all()
            return [self._to_domain(m) for m in models], total

    def find_all_dict(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        """返回 (dict 行列表, total)。"""
        import re
        from typing import Any

        with get_db() as db:
            offset = (page - 1) * per_page
            query = db.query(ProductModel)
            unit_name = kwargs.get("unit_name")
            if unit_name:
                query = query.filter(ProductModel.unit == unit_name)
            model_number = kwargs.get("model_number")
            if model_number:
                from sqlalchemy import or_

                pattern = f"%{str(model_number).strip()}%"
                query = query.filter(
                    or_(
                        ProductModel.model_number.like(pattern),
                        ProductModel.name.like(pattern),
                    )
                )
            keyword = kwargs.get("keyword")
            if keyword:
                from sqlalchemy import func, or_

                keyword_text = str(keyword).strip()
                u = func.coalesce(ProductModel.unit, "")
                n = func.coalesce(ProductModel.name, "")
                m = func.coalesce(ProductModel.model_number, "")
                s = func.coalesce(ProductModel.specification, "")
                concat_blob = u.op("||")(n).op("||")(m).op("||")(s)

                def _one_kw(kw: str) -> Any:
                    k = str(kw).strip()
                    if not k:
                        return None
                    tok = k.upper().replace("-", "").replace(" ", "")
                    nm = func.upper(
                        func.replace(
                            func.replace(func.coalesce(ProductModel.model_number, ""), "-", ""),
                            " ",
                            "",
                        )
                    )
                    return or_(
                        ProductModel.unit.like(f"%{k}%"),
                        ProductModel.name.like(f"%{k}%"),
                        ProductModel.model_number.like(f"%{k}%"),
                        ProductModel.specification.like(f"%{k}%"),
                        nm.like(f"%{tok}%"),
                        concat_blob.like(f"%{k}%"),
                    )

                segments = re.findall(r"[\u4e00-\u9fff]+|[0-9]+|[A-Za-z]+", keyword_text)
                segments = [p for p in segments if p.strip()]
                if len(segments) > 1:
                    for seg in segments:
                        filt = _one_kw(seg)
                        if filt is not None:
                            query = query.filter(filt)
                else:
                    kw_use = segments[0] if segments else keyword_text
                    filt = _one_kw(kw_use if kw_use else keyword_text)
                    if filt is not None:
                        query = query.filter(filt)

            total = query.count()
            models = query.order_by(ProductModel.id.desc()).limit(per_page).offset(offset).all()
            dicts = [
                {
                    "id": m.id,
                    "model_number": m.model_number or "",
                    "name": m.name or "",
                    "specification": m.specification or "",
                    "price": m.price or 0,
                    "quantity": m.quantity or 0,
                    "description": m.description or "",
                    "category": m.category or "",
                    "brand": m.brand or "",
                    "unit": m.unit or "个",
                    "is_active": bool(m.is_active),
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                }
                for m in models
            ]
            return dicts, total

    def find_by_model_number(self, model_number: str) -> Product | None:
        with get_db() as db:
            model = db.query(ProductModel).filter(ProductModel.model_number == model_number).first()
            return self._to_domain(model) if model else None

    def find_by_name(self, name: str) -> list[Product]:
        with get_db() as db:
            models = db.query(ProductModel).filter(ProductModel.name.like(f"%{name}%")).all()
            return [self._to_domain(m) for m in models]

    def delete(self, product_id: int) -> bool:
        return SQLAlchemyProductRepository().delete(product_id)

    def count(self) -> int:
        return SQLAlchemyProductRepository().count()

    def find_product_units(self) -> list[str]:
        return SQLAlchemyProductRepository().find_product_units()
