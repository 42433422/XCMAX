import re
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import inspect

from app.db.models import Product as ProductModel
from app.db.session import get_db
from app.infrastructure.persistence.product_repository_impl import TRIVIAL_MEASURE_UNITS
from app.domain.product.entities import Product
from app.domain.value_objects import ModelNumber, Money
from app.infrastructure.repositories.product_repository import ProductRepository


class SQLAlchemyProductRepository(ProductRepository):
    """产品仓储 SQLAlchemy 实现"""
    
    def _to_domain(self, db_model: ProductModel) -> Product:
        return Product(
            id=db_model.id,
            model_number=ModelNumber(db_model.model_number) if db_model.model_number else None,
            name=db_model.name or "",
            specification=db_model.specification or "",
            price=Money(db_model.price or 0),
            quantity=db_model.quantity or 0,
            description=db_model.description or "",
            category=db_model.category or "",
            brand=db_model.brand or "",
            unit=db_model.unit or "个",
            is_active=bool(db_model.is_active),
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )
    
    def _to_db_model(self, product: Product) -> dict:
        return {
            "name": product.name,
            "model_number": str(product.model_number) if product.model_number else None,
            "specification": product.specification,
            "price": product.price.amount,
            "quantity": product.quantity,
            "description": product.description,
            "category": product.category,
            "brand": product.brand,
            "unit": product.unit,
            "is_active": 1 if product.is_active else 0,
        }
    
    def save(self, product: Product) -> Product:
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

    def find_by_id(self, product_id: int) -> Optional[Product]:
        with get_db() as db:
            model = db.query(ProductModel).filter(ProductModel.id == product_id).first()
            return self._to_domain(model) if model else None
    
    def find_all(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        with get_db() as db:
            offset = (page - 1) * per_page
            query = db.query(ProductModel)

            unit_name = kwargs.get('unit_name')
            if unit_name:
                query = query.filter(ProductModel.unit == unit_name)

            model_number = kwargs.get('model_number')
            if model_number:
                model_token = str(model_number).strip()
                if model_token:
                    from sqlalchemy import or_
                    pattern = f"%{model_token}%"
                    # 优先通过型号字段匹配；兼容历史数据中型号写在名称里的情况。
                    query = query.filter(
                        or_(
                            ProductModel.model_number.like(pattern),
                            ProductModel.name.like(pattern),
                        )
                    )

            keyword = kwargs.get('keyword')
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

                segments = re.findall(
                    r"[\u4e00-\u9fff]+|[0-9]+|[A-Za-z]+", keyword_text
                )
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
            models = query.order_by(
                ProductModel.id.desc()
            ).limit(per_page).offset(offset).all()
            return [self._to_domain(m) for m in models], total

    def find_all_dict(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        """快速查询，返回字典列表（避免 Domain 对象转换开销）"""
        with get_db() as db:
            offset = (page - 1) * per_page
            query = db.query(ProductModel)

            unit_name = kwargs.get('unit_name')
            if unit_name:
                query = query.filter(ProductModel.unit == unit_name)

            model_number = kwargs.get('model_number')
            if model_number:
                model_token = str(model_number).strip()
                if model_token:
                    from sqlalchemy import or_
                    pattern = f"%{model_token}%"
                    query = query.filter(
                        or_(
                            ProductModel.model_number.like(pattern),
                            ProductModel.name.like(pattern),
                        )
                    )

            keyword = kwargs.get('keyword')
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

                segments = re.findall(
                    r"[\u4e00-\u9fff]+|[0-9]+|[A-Za-z]+", keyword_text
                )
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
            models = query.order_by(
                ProductModel.id.desc()
            ).limit(per_page).offset(offset).all()

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

    def find_by_model_number(self, model_number: str) -> Optional[Product]:
        with get_db() as db:
            model = db.query(ProductModel).filter(
                ProductModel.model_number == model_number
            ).first()
            return self._to_domain(model) if model else None
    
    def find_by_name(self, name: str) -> List[Product]:
        with get_db() as db:
            models = db.query(ProductModel).filter(
                ProductModel.name.like(f"%{name}%")
            ).all()
            return [self._to_domain(m) for m in models]
    
    def delete(self, product_id: int) -> bool:
        with get_db() as db:
            model = db.query(ProductModel).filter(ProductModel.id == product_id).first()
            if model:
                db.delete(model)
                db.commit()
                return True
            return False
    
    def count(self) -> int:
        with get_db() as db:
            return db.query(ProductModel).count()

    def find_product_units(self) -> List[str]:
        """与 persistence.SQLAlchemyProductRepository.find_product_units 行为对齐。"""
        seen: dict[str, None] = {}
        ordered: List[str] = []

        def add_label(raw: Any, *, from_products: bool = False) -> None:
            s = str(raw or "").strip()
            if not s or s in seen:
                return
            if from_products and s in TRIVIAL_MEASURE_UNITS:
                return
            seen[s] = None
            ordered.append(s)

        purchase_units_authoritative = False
        try:
            from app.application.customer_app_service import get_customers_session
            from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel

            cs = get_customers_session()
            try:
                bind = getattr(cs, "bind", None) or cs.get_bind()
                if bind is not None:
                    tinsp = inspect(bind)
                    if "purchase_units" in (tinsp.get_table_names() or []):
                        purchase_units_authoritative = True
                        for r in (
                            cs.query(PurchaseUnitModel.unit_name)
                            .filter(PurchaseUnitModel.unit_name.isnot(None))
                            .filter(PurchaseUnitModel.is_active.is_(True))
                            .distinct()
                            .all()
                        ):
                            if r and r[0] is not None:
                                add_label(r[0], from_products=False)
            finally:
                cs.close()
        except Exception:
            pass

        if purchase_units_authoritative:
            return ordered

        try:
            with get_db() as db:
                insp = inspect(db.bind)
                if "products" in (insp.get_table_names() or []):
                    for u in db.query(ProductModel.unit).distinct().all():
                        if u and u[0] is not None:
                            add_label(u[0], from_products=True)
        except Exception:
            pass

        return ordered
