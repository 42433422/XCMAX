"""Legacy shipment-document generation adapter."""

from __future__ import annotations

from app.application.ports.shipment_document_generator import ShipmentDocumentGeneratorPort
from app.utils.mixin_module_sync import sync_mixin_methods


class LegacyShipmentDocumentGenerator(ShipmentDocumentGeneratorPort):
    """
    基于旧版 AI助手/shipment_document.py 的文档生成适配器。

    约束：
    - 产品匹配只使用主库 `products` 表（不再走客户专属 sqlite 库）
    - 单位名统一从 `customers` 解析/规范化
    """

    def __init__(self):
        # 模板/外部资源统一放在 XCAGI/resources 下，避免依赖项目外目录
        # 兼容期：如果 resources 下不存在，再回退到 XCAGI/AI助手/uploads（仍在项目内）
        from app.utils.path_utils import get_resource_path

        resources_template_dir = get_resource_path("ai_assistant", "uploads")
        legacy_template_dir = os.path.join(get_base_dir(), "AI助手", "uploads")
        self.template_dir = (
            resources_template_dir if os.path.isdir(resources_template_dir) else legacy_template_dir
        )
        self.output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")
        os.makedirs(self.output_dir, exist_ok=True)

    def _load_products_from_main_db(self, *, unit_name: str) -> list[dict[str, Any]]:
        """Load only products that belong to the resolved customer in this tenant.

        A model number is not globally meaningful in the desktop product master.
        The ETL aggregate writes products under ``Product.unit`` and chat order
        generation must preserve that same customer-product relationship rather
        than letting a product from another customer fill a delivery note.
        """
        products: list[dict[str, Any]] = []
        with get_db() as db:
            rows = (
                apply_tenant_filter(db.query(Product), Product)
                .filter(Product.is_active == 1, Product.unit == str(unit_name or "").strip())
                .all()
            )
            for p in rows:
                products.append(
                    {
                        "id": p.id,
                        "model_number": p.model_number or "",
                        "name": p.name or "",
                        "price": float(p.price) if p.price else 0.0,
                        "specification": p.specification or "",
                        "brand": p.brand or "",
                        "unit": p.unit or "",
                    }
                )
        return products

    def generate(
        self,
        *,
        unit_name: str,
        products: list[dict[str, Any]],
        date: str | None = None,
        template_name: str | None = None,
        order_number: str | None = None,
        owner_user_id: int | None = None,
        tenant_id: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        # 1) 统一单位名来源：purchase_units 主库
        resolved = resolve_purchase_unit(unit_name)
        if not resolved:
            return {
                "success": False,
                "message": f"未找到客户：{unit_name}",
                "doc_name": None,
                "file_path": None,
            }

        # 2) 加载 legacy 生成器
        loaded = load_legacy_shipment_document_generator(caller_file=__file__)
        ShipmentDocumentGenerator = loaded.ShipmentDocumentGenerator
        PurchaseUnitInfo = loaded.PurchaseUnitInfo

        # 3) 构造 purchase_unit_info
        purchase_unit_info = PurchaseUnitInfo(
            name=resolved.unit_name,
            contact_person=resolved.contact_person,
            contact_phone=resolved.contact_phone,
            address=resolved.address,
            id=resolved.id,
        )

        # 4) 产品匹配（仅主库 products）
        db_products = self._load_products_from_main_db(unit_name=resolved.unit_name)
        parsed_products: list[dict[str, Any]] = prepare_parsed_products(
            input_products=products,
            db_products=db_products,
        )

        if not parsed_products:
            return {
                "success": False,
                "message": "产品列表为空或无有效产品名称",
                "doc_name": None,
                "file_path": None,
            }

        parsed_data: dict[str, Any] = {
            "purchase_unit": resolved.unit_name,
            "products": parsed_products,
        }

        # 5) 调用 legacy 生成逻辑
        from app.db.init_db import get_db_path

        generator = ShipmentDocumentGenerator(db_path=get_db_path("products.db"))
        template_path = str(template_name or "").strip()
        if template_path and os.path.isfile(template_path):
            from app.infrastructure.documents.shipment_workbook_filler import (
                fill_shipment_workbook,
                safe_shipment_filename,
            )

            resolved_order_number = (
                str(order_number or "").strip() or generator._generate_order_number()
            )
            output_path = os.path.join(
                self.output_dir,
                safe_shipment_filename(resolved_order_number),
            )
            info = fill_shipment_workbook(
                template_path,
                output_path=output_path,
                unit_name=resolved.unit_name,
                contact_person=resolved.contact_person or "",
                products=parsed_products,
                order_number=resolved_order_number,
                date=date,
            )
            file_path = info.get("filepath")
            file_path = file_path or info.get("file_path")
            filename = info.get("filename") or (os.path.basename(file_path) if file_path else "")
            order_number = info.get("order_number") or resolved_order_number
            total_amount = info.get("total_amount")
            total_quantity = info.get("total_quantity")
        else:
            doc = generator.generate_document(
                order_text="",
                parsed_data=parsed_data,
                purchase_unit=purchase_unit_info,
                template_name=template_name,
                custom_order_number=order_number,
            )
            if hasattr(doc, "to_dict"):
                info = doc.to_dict()
                file_path = info.get("filepath")
                filename = info.get("filename") or (
                    os.path.basename(file_path) if file_path else ""
                )
                order_number = info.get("order_number")
                total_amount = info.get("total_amount")
                total_quantity = info.get("total_quantity")
            else:
                file_path = getattr(doc, "filepath", None)
                filename = getattr(
                    doc,
                    "filename",
                    os.path.basename(file_path) if file_path else "",
                )
                order_number = getattr(doc, "order_number", None)
                total_amount = getattr(doc, "total_amount", None)
                total_quantity = getattr(doc, "total_quantity", None)

        # 6) 生成标签图片。资源目录只放只读模板，不能作为安装版输出目录。
        labels_dir, label_run_id = get_shipment_label_output_dir(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            run_id=run_id,
        )
        label_generator = SimpleLabelGenerator(labels_dir)
        generated_labels = label_generator.generate_labels_for_order(
            order_number=order_number or filename.replace(".xlsx", ""), products=parsed_products
        )

        return {
            "success": True,
            "message": "发货单生成成功",
            "doc_name": filename,
            "file_path": file_path,
            "order_number": order_number,
            "total_amount": total_amount,
            "total_quantity": total_quantity,
            "purchase_unit": resolved.unit_name,
            "unit_id": resolved.id,
            "parsed_products": parsed_products,
            "labels": generated_labels,
            "label_run_id": label_run_id,
        }


sync_mixin_methods(
    LegacyShipmentDocumentGenerator,
    target=globals(),
    source_module="app.infrastructure.documents.shipment_document_generator_impl",
    method_names=(
        "__init__",
        "_load_products_from_main_db",
        "generate",
    ),
)
