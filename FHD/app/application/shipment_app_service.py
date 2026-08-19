import logging
import os
from datetime import datetime
from typing import Any

from app.application.ports import (
    PurchaseUnitQueryPort,
    ShipmentDocumentGeneratorPort,
    ShipmentRecordCommandPort,
    ShipmentRecordQueryPort,
    ShipmentRecordStorePort,
    ShipmentRepository,
)
from app.application.shipment_document_workflows import ShipmentDocumentWorkflowMixin
from app.domain.shipment.aggregates import Shipment, ShipmentItem
from app.legacy.domain.legacy_vo import ContactInfo
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ShipmentApplicationService(ShipmentDocumentWorkflowMixin):
    """发货单应用服务 - 用例编排"""

    def __init__(
        self,
        repository: ShipmentRepository,
        document_generator: ShipmentDocumentGeneratorPort | None = None,
        record_store: ShipmentRecordStorePort | None = None,
        record_query: ShipmentRecordQueryPort | None = None,
        record_command: ShipmentRecordCommandPort | None = None,
        purchase_unit_query: PurchaseUnitQueryPort | None = None,
    ):
        self._repository = repository
        self._document_generator = document_generator
        self._record_store = record_store
        self._record_query = record_query
        self._record_command = record_command
        self._purchase_unit_query = purchase_unit_query

    def create_shipment(
        self,
        unit_name: str,
        items_data: list[dict[str, Any]],
        contact_person: str = "",
        contact_phone: str = "",
        external_order_number: str = "",
        order_date: str = "",
        source_fingerprint: str = "",
        source_kind: str = "",
    ) -> dict[str, Any]:
        """
        创建发货单用例。

        external_order_number / order_date 写入 raw_text 元数据，便于 ETL 追溯；
        系统主键仍由仓储分配（历史兼容）。
        """
        try:
            contact_info = ContactInfo(person=contact_person, phone=contact_phone)
            shipment = Shipment.create(unit_name=unit_name, contact_info=contact_info)

            for item_data in items_data:
                try:
                    item = ShipmentItem.from_dict(item_data)
                    shipment.add_item(item)
                except ValueError as e:
                    logger.warning("跳过无效产品: %s", e)
                    continue

            if not shipment.is_valid():
                return {"success": False, "message": "发货单无效：缺少购买单位或产品"}

            meta_parts = ["source=shipment_excel_etl"]
            if str(external_order_number or "").strip():
                meta_parts.append(f"external_order_number={str(external_order_number).strip()}")
            if str(order_date or "").strip():
                meta_parts.append(f"order_date={str(order_date).strip()}")
            if str(source_fingerprint or "").strip():
                meta_parts.append(f"fingerprint={str(source_fingerprint).strip()}")
            if str(source_kind or "").strip():
                meta_parts.append(f"source_kind={str(source_kind).strip()}")
            shipment.raw_text = "|".join(meta_parts)

            saved_shipment = self._repository.save(shipment)

            try:
                from app.infrastructure.mods.hooks import trigger

                trigger("shipment.created", shipment=saved_shipment)
            except RECOVERABLE_ERRORS as hook_err:
                logger.warning("Hook trigger failed: %s", hook_err)

            payload = saved_shipment.to_dict()
            if str(external_order_number or "").strip():
                payload["external_order_number"] = str(external_order_number).strip()
            if str(order_date or "").strip():
                payload["order_date"] = str(order_date).strip()

            return {
                "success": True,
                "message": "发货单创建成功",
                "shipment": payload,
            }

        except RECOVERABLE_ERRORS as e:
            logger.exception("创建发货单失败: %s", e)
            return {"success": False, "message": f"创建失败: {str(e)}"}

    def get_shipment(self, shipment_id: int) -> Shipment | None:
        """获取发货单"""
        return self._repository.find_by_id(shipment_id)

    def list_shipments(
        self,
        unit_name: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """查询发货单列表"""
        try:
            shipments = self._repository.find_all(page=page, per_page=per_page)

            if unit_name:
                shipments = self._repository.find_by_unit(unit_name)

            total = self._repository.count()

            return {
                "success": True,
                "data": [s.to_dict() for s in shipments],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

        except RECOVERABLE_ERRORS as e:
            logger.exception("查询发货单失败: %s", e)
            return {"success": False, "message": str(e), "data": []}

    def query_shipment_orders(
        self,
        unit_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """
        出货记录列表查询（read side），保持与旧接口返回结构一致。
        """
        if not self._record_query:
            return {
                "success": False,
                "message": "record_query 未配置",
                "data": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
            }

        return self._record_query.query_shipments(
            unit_name=unit_name,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )

    def search_orders(self, query: str) -> list[dict[str, Any]]:
        """搜索出货记录（read side）。"""
        if not self._record_query:
            return []
        return self._record_query.search_shipments(query)

    def get_order(self, order_number: str) -> dict[str, Any] | None:
        """根据 id 查询出货记录（用于 GET /orders/<order_number>）。"""
        if not self._record_query:
            return None
        return self._record_query.get_shipment_by_id(order_number)

    def get_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近创建的出货记录（用于 GET /orders/latest）。"""
        if not self._record_query:
            return []
        return self._record_query.get_latest_shipments(limit)

    def get_purchase_units(self) -> list[str]:
        """获取所有购买单位列表（用于 /orders/purchase-units）。"""
        if not self._purchase_unit_query:
            return []
        return self._purchase_unit_query.list_purchase_units()

    def clear_shipment_by_unit(self, purchase_unit: str) -> dict[str, Any]:
        """清理指定购买单位的出货记录。"""
        if not self._record_command:
            return {"success": False, "message": "record_command 未配置"}
        return self._record_command.clear_by_unit(purchase_unit)

    def clear_all_orders(self) -> dict[str, Any]:
        """清空所有出货记录。"""
        if not self._record_command:
            return {"success": False, "message": "record_command 未配置"}
        return self._record_command.clear_all()

    def get_shipment_records(
        self, unit_name: str | None = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """后台：获取出货记录列表（/shipment-records/records）。"""
        if not self._record_query:
            return []
        return self._record_query.get_shipment_records(unit_name, limit=limit)

    def update_shipment_record(
        self,
        record_id: int,
        *,
        unit_name: str | None = None,
        products: list[dict[str, Any]] | None = None,
        date: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        后台：更新出货记录。
        兼容旧接口：products 参数保留但当前不会用于修改 parsed/products 字段（沿用旧实现的行为）。
        """
        if not self._record_command:
            return {"success": False, "message": "record_command 未配置"}

        # 将旧实现里的 kwargs 全量传给 record 字段（排除 products/date/unit_name）
        fields = dict(kwargs)
        return self._record_command.update_record(
            record_id,
            unit_name=unit_name,
            date=date,
            fields=fields,
        )

    def delete_shipment_record(self, record_id: int) -> dict[str, Any]:
        """后台：删除出货记录（/shipment-records/record DELETE）。"""
        if not self._record_command:
            return {"success": False, "message": "record_command 未配置"}
        return self._record_command.delete_record(record_id)


    def set_order_sequence(self, sequence: int) -> dict[str, Any]:
        """设置订单序号（兼容旧接口，无状态实现）。"""
        return {"success": True, "message": "序号已设置", "sequence": int(sequence)}

    def reset_order_sequence(self) -> dict[str, Any]:
        """重置订单序号（兼容旧接口，无状态实现）。"""
        return {"success": True, "message": "序号已重置", "sequence": 1}

    def download_shipment_order(self, filename: str) -> dict[str, Any]:
        """检查发货单文件是否存在（兼容旧接口）。"""
        from app.utils.path_io.path_utils import get_app_data_dir

        output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")
        file_path = os.path.join(output_dir, filename)
        if not os.path.exists(file_path):
            return {"success": False, "message": f"文件不存在：{filename}", "file_path": None}
        return {"success": True, "file_path": file_path, "message": "文件存在"}

    def mark_as_printed(self, shipment_id: int, printer_name: str = "") -> dict[str, Any]:
        """标记发货单为已打印"""
        try:
            shipment = self._repository.find_by_id(shipment_id)
            if not shipment:
                return {"success": False, "message": "发货单不存在"}

            shipment.mark_as_printed(printer_name)
            self._repository.save(shipment)

            return {
                "success": True,
                "message": "已标记为已打印",
                "printed_at": datetime.now().isoformat(),
            }

        except RECOVERABLE_ERRORS as e:
            logger.exception("标记打印失败: %s", e)
            return {"success": False, "message": str(e)}

    def cancel_shipment(self, shipment_id: int) -> dict[str, Any]:
        """取消发货单"""
        try:
            shipment = self._repository.find_by_id(shipment_id)
            if not shipment:
                return {"success": False, "message": "发货单不存在"}

            shipment.cancel()
            self._repository.save(shipment)

            return {"success": True, "message": "发货单已取消"}

        except RECOVERABLE_ERRORS as e:
            logger.exception("取消发货单失败: %s", e)
            return {"success": False, "message": str(e)}

    def delete_shipment(self, shipment_id: int) -> dict[str, Any]:
        """删除发货单"""
        try:
            success = self._repository.delete(shipment_id)
            if success:
                return {"success": True, "message": "发货单已删除"}
            return {"success": False, "message": "发货单不存在"}

        except RECOVERABLE_ERRORS as e:
            logger.exception("删除发货单失败: %s", e)
            return {"success": False, "message": str(e)}

    def calculate_totals(self, items_data: list[dict[str, Any]]) -> dict[str, Any]:
        """计算发货单汇总"""
        total_amount = 0.0
        total_tins = 0
        total_kg = 0.0

        for item_data in items_data:
            tins = item_data.get("quantity_tins", 0)
            spec = item_data.get("tin_spec", 10.0)
            kg = tins * spec
            price = item_data.get("unit_price", 0)

            total_tins += tins
            total_kg += kg
            total_amount += price * kg

        return {
            "total_tins": total_tins,
            "total_kg": total_kg,
            "total_amount": total_amount,
        }

    def get_latest_products_for_unit(
        self, unit_name: str, *, limit: int = 1
    ) -> list[dict[str, Any]]:
        """返回指定客户最近出货记录中的产品明细（打单缺货明细兜底）。"""
        name = str(unit_name or "").strip()
        if not name:
            return []
        orders = self.get_orders(max(20, int(limit) * 5)) or []
        matched: list[dict[str, Any]] = []
        for order in orders:
            if not isinstance(order, dict):
                continue
            customer = str(
                order.get("customer_name")
                or order.get("unit_name")
                or order.get("purchase_unit")
                or ""
            ).strip()
            if not customer:
                continue
            if not (customer == name or name in customer or customer in name):
                continue
            items = order.get("products") or order.get("items") or []
            if isinstance(items, list) and items:
                matched.append({"order": order, "products": list(items)})
                if len(matched) >= max(1, int(limit)):
                    break
        if not matched:
            return []
        return list(matched[0]["products"])



from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(ShipmentApplicationService)


def get_shipment_application_service() -> ShipmentApplicationService:
    """获取发货服务单例（与 ``app.bootstrap.get_shipment_application_service_core`` 同源）。"""
    from app.bootstrap import get_shipment_application_service_core

    return get_shipment_application_service_core()
