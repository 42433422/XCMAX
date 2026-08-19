import logging
from datetime import datetime
from typing import Any, cast

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Product as ProductModel
from app.db.session import get_db
from app.domain.product.entities import Product
from app.infrastructure.mappers.product_mapper import product_to_db, product_to_domain
from app.infrastructure.repositories.product_query_helpers import (
    TRIVIAL_MEASURE_UNITS,
    apply_product_filters,
)
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.product_repository_export_mixin import ProductExportMixin
from app.infrastructure.tenant_scope import apply_tenant_filter, tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_REPOSITORY_ERRORS = RECOVERABLE_ERRORS


class SQLAlchemyProductRepository(ProductRepository, ProductExportMixin):
    """产品仓储 SQLAlchemy 实现"""

    def _to_domain(self, db_model: ProductModel) -> Product:
        return product_to_domain(db_model)

    def _to_db_model(self, product: Product) -> dict:
        return product_to_db(product)

    def save(self, product: Product) -> Product:
        with get_db() as db:
            if product.id:
                existing = (
                    apply_tenant_filter(db.query(ProductModel), ProductModel)
                    .filter(ProductModel.id == product.id)
                    .first()
                )
                if existing:
                    for key, value in self._to_db_model(product).items():
                        setattr(existing, key, value)
                    existing.updated_at = datetime.now()
                    db.commit()
                    db.refresh(existing)
                    return self._to_domain(existing)

            db_model = ProductModel(**self._to_db_model(product))
            if getattr(db_model, "tenant_id", None) is None:
                db_model.tenant_id = tenant_id_for_write()
            db.add(db_model)
            db.commit()
            db.refresh(db_model)
            return self._to_domain(db_model)

    def create(self, product):
        # 兼容 dict 或 domain 输入：products_service 先尝试 create(payload_dict)，
        # 失败后再回退到 create(domain)。此处统一分发，避免调用方捕获 AttributeError。
        if isinstance(product, dict):
            return self.create_from_dict(product)
        return self.save(product)

    def find_by_id(self, product_id: int) -> Product | None:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(ProductModel), ProductModel)
                .filter(ProductModel.id == product_id)
                .first()
            )
            return self._to_domain(model) if model else None

    def find_all(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        with get_db() as db:
            offset = (page - 1) * per_page
            query = apply_tenant_filter(db.query(ProductModel), ProductModel)
            query = apply_product_filters(query, **kwargs)

            total = query.count()
            models = query.order_by(ProductModel.id.desc()).limit(per_page).offset(offset).all()
            return [self._to_domain(m) for m in models], total

    def find_all_dict(self, page: int = 1, per_page: int = 20, **kwargs) -> tuple:
        """快速查询，返回字典列表（避免 Domain 对象转换开销）"""
        with get_db() as db:
            offset = (page - 1) * per_page
            query = apply_tenant_filter(db.query(ProductModel), ProductModel)
            query = apply_product_filters(query, **kwargs)

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
            model = (
                apply_tenant_filter(db.query(ProductModel), ProductModel)
                .filter(ProductModel.model_number == model_number)
                .first()
            )
            return self._to_domain(model) if model else None

    def find_by_name(self, name: str) -> list[Product]:
        with get_db() as db:
            models = (
                apply_tenant_filter(db.query(ProductModel), ProductModel)
                .filter(ProductModel.name.like(f"%{name}%"))
                .all()
            )
            return [self._to_domain(m) for m in models]

    def delete(self, product_id: int) -> bool:
        with get_db() as db:
            model = (
                apply_tenant_filter(db.query(ProductModel), ProductModel)
                .filter(ProductModel.id == product_id)
                .first()
            )
            if model:
                db.delete(model)
                db.commit()
                return True
            return False

    def count(self) -> int:
        with get_db() as db:
            return cast("int", apply_tenant_filter(db.query(ProductModel), ProductModel).count())

    def find_product_units(self) -> list[str]:
        """与 persistence.SQLAlchemyProductRepository.find_product_units 行为对齐。"""
        seen: dict[str, None] = {}
        ordered: list[str] = []

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
        except RECOVERABLE_ERRORS:
            logger.debug("suppressed exception", exc_info=True)

        if purchase_units_authoritative:
            return ordered

        try:
            with get_db() as db:
                insp = inspect(db.bind)
                if "products" in (insp.get_table_names() or []):
                    for u in db.query(ProductModel.unit).distinct().all():
                        if u and u[0] is not None:
                            add_label(u[0], from_products=True)
        except RECOVERABLE_ERRORS:
            logger.debug("suppressed exception", exc_info=True)

        return ordered

    def create_from_dict(self, item: dict[str, Any]) -> dict[str, Any]:
        """按 dict 创建单条产品（批量/兼容路径用），返回契约与原 dict 版 create 一致。"""
        try:
            product_name = item.get("product_name") or item.get("name")
            price = item.get("price", 0.0)
            description = item.get("description", "")

            if not product_name:
                return {"success": False, "message": "产品名称不能为空"}

            with get_db() as db:
                product = ProductModel(
                    name=product_name,
                    price=price,
                    description=description,
                    model_number=item.get("model_number"),
                    specification=item.get("specification"),
                    quantity=item.get("quantity"),
                    category=item.get("category"),
                    brand=item.get("brand"),
                    unit=item.get("unit", "个"),
                    is_active=item.get("is_active", 1),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(product)
                db.commit()
                db.refresh(product)
                product_id = product.id

            return {"success": True, "message": "产品创建成功", "product_id": product_id}

        except _REPOSITORY_ERRORS as e:
            return {"success": False, "message": f"创建失败：{str(e)}"}

    def update(self, product_id: int, data: dict[str, Any]) -> dict[str, Any]:
        try:
            with get_db() as db:
                product = (
                    apply_tenant_filter(db.query(ProductModel), ProductModel)
                    .filter(ProductModel.id == product_id)
                    .first()
                )

                if not product:
                    return {"success": False, "message": "产品不存在"}

                has_update = False
                if "product_name" in data or "name" in data:
                    product.name = data.get("product_name") or data.get("name")
                    has_update = True
                if "price" in data:
                    product.price = data["price"]
                    has_update = True
                if "description" in data:
                    product.description = data["description"]
                    has_update = True
                if "model_number" in data:
                    product.model_number = data["model_number"]
                    has_update = True
                if "specification" in data:
                    product.specification = data["specification"]
                    has_update = True
                if "quantity" in data:
                    product.quantity = data["quantity"]
                    has_update = True
                if "category" in data:
                    product.category = data["category"]
                    has_update = True
                if "brand" in data:
                    product.brand = data["brand"]
                    has_update = True
                if "unit" in data:
                    product.unit = data["unit"]
                    has_update = True
                if "is_active" in data:
                    product.is_active = data["is_active"]
                    has_update = True

                if not has_update:
                    return {"success": False, "message": "没有要更新的字段"}

                product.updated_at = datetime.now()
                db.commit()

            return {"success": True, "message": "产品更新成功"}

        except _REPOSITORY_ERRORS as e:
            return {"success": False, "message": f"更新失败：{str(e)}"}

    def batch_create(self, products_data: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            if not products_data:
                return {"success": False, "message": "产品列表不能为空"}

            success_count = 0
            failed_products = []
            product_ids = []

            batch_size = 100
            now = datetime.now()
            tenant_id = tenant_id_for_write()

            with get_db() as db:
                for batch_start in range(0, len(products_data), batch_size):
                    batch = products_data[batch_start : batch_start + batch_size]
                    batch_records = []

                    for index, data in enumerate(batch):
                        try:
                            product_name = data.get("product_name") or data.get("name")
                            price = data.get("price", 0.0)
                            description = data.get("description", "")

                            if not product_name:
                                failed_products.append(
                                    {"index": batch_start + index, "reason": "产品名称不能为空"}
                                )
                                continue

                            batch_records.append(
                                {
                                    "name": product_name,
                                    "price": price,
                                    "description": description,
                                    "model_number": data.get("model_number"),
                                    "specification": data.get("specification"),
                                    "quantity": data.get("quantity"),
                                    "category": data.get("category"),
                                    "brand": data.get("brand"),
                                    "unit": data.get("unit", "个"),
                                    "is_active": data.get("is_active", 1),
                                    "tenant_id": tenant_id,
                                    "created_at": now,
                                    "updated_at": now,
                                }
                            )

                        except RECOVERABLE_ERRORS as e:
                            failed_products.append({"index": batch_start + index, "reason": str(e)})

                    if batch_records:
                        try:
                            db.bulk_insert_mappings(ProductModel, batch_records)
                            db.commit()
                            success_count += len(batch_records)
                        except SQLAlchemyError:
                            db.rollback()
                            for idx, record in enumerate(batch_records):
                                try:
                                    product = ProductModel(**record)
                                    db.add(product)
                                    db.flush()
                                    product_ids.append(product.id)
                                    success_count += 1
                                except RECOVERABLE_ERRORS:
                                    failed_products.append(
                                        {"index": batch_start + idx, "reason": "单条插入失败"}
                                    )
                            db.commit()

            result = {
                "success": len(failed_products) == 0,
                "message": (
                    f"成功添加 {success_count} 个产品，失败 {len(failed_products)} 个"
                    if failed_products
                    else f"成功添加 {success_count} 个产品"
                ),
                "success_count": success_count,
                "failed_count": len(failed_products),
                "product_ids": product_ids,
            }

            if failed_products:
                result["failed_products"] = failed_products[:50]

            return result

        except _REPOSITORY_ERRORS as e:
            return {"success": False, "message": f"批量添加失败：{str(e)}"}

    def batch_delete(self, product_ids: list[int]) -> dict[str, Any]:
        try:
            if not product_ids:
                return {"success": False, "message": "产品 ID 列表不能为空"}

            with get_db() as db:
                products = (
                    apply_tenant_filter(db.query(ProductModel), ProductModel)
                    .filter(ProductModel.id.in_(product_ids))
                    .all()
                )

                if not products:
                    return {"success": False, "message": "未找到要删除的产品"}

                for product in products:
                    db.delete(product)

                db.commit()

                return {
                    "success": True,
                    "message": f"成功删除 {len(products)} 个产品",
                    "deleted_count": len(products),
                }

        except _REPOSITORY_ERRORS as e:
            return {"success": False, "message": f"批量删除失败：{str(e)}"}

    def exists(self, product_id: int) -> bool:
        try:
            with get_db() as db:
                product = (
                    apply_tenant_filter(db.query(ProductModel), ProductModel)
                    .filter(ProductModel.id == product_id)
                    .first()
                )
                return product is not None
        except _REPOSITORY_ERRORS:
            return False

    def find_names(self, keyword: str | None = None) -> list[str]:
        try:
            with get_db() as db:
                inspector = inspect(db.bind)
                if "products" not in inspector.get_table_names():
                    return []

                query = db.query(ProductModel.name)

                if keyword:
                    query = query.filter(ProductModel.name.like(f"%{keyword}%"))

                query = query.distinct()
                names = [row[0] for row in query.all() if row[0]]

                return names

        except _REPOSITORY_ERRORS:
            return []
