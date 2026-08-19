"""
数据导入服务模块

提供从 Excel 提取的数据导入到数据库的服务。
"""

import logging
from datetime import datetime
from typing import Any

from app.db.models import Product
from app.db.session import get_db
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ProductImportService(NeuroEventPublisherMixin):
    """产品数据导入服务类"""

    def __init__(self):
        """初始化产品导入服务"""
        pass

    def clean_data(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        清洗数据

        Args:
            data: 原始数据列表

        Returns:
            清洗后的数据列表
        """
        cleaned = []
        for row in data:
            cleaned_row = {}
            for key, value in row.items():
                # 去除字符串两端空格
                if isinstance(value, str):
                    value = value.strip()
                # 处理空值
                if value == "" or value is None:
                    value = None
                cleaned_row[key] = value
            cleaned.append(cleaned_row)
        return cleaned

    def validate_data(self, data: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        """
        验证数据

        Args:
            data: 数据列表

        Returns:
            (valid_data, invalid_data) 有效数据和无效数据
        """
        valid = []
        invalid = []

        for row in data:
            errors = []

            # 检查必填字段
            if not row.get("product_code") and not row.get("product_name"):
                errors.append("产品编码或产品名称不能同时为空")

            # 检查价格格式
            if "unit_price" in row and row["unit_price"] is not None:
                try:
                    price = float(row["unit_price"])
                    if price < 0:
                        errors.append("单价不能为负数")
                except (ValueError, TypeError):
                    errors.append("单价格式不正确")

            if errors:
                invalid.append({"data": row, "errors": errors})
            else:
                valid.append(row)

        return valid, invalid

    def check_duplicates(
        self, data: list[dict[str, Any]], skip_duplicates: bool = True
    ) -> tuple[list[dict], list[dict]]:
        """
        检查重复数据

        Args:
            data: 数据列表
            skip_duplicates: 是否跳过重复项

        Returns:
            (new_data, duplicates) 新数据和重复数据
        """
        if not data:
            return [], []

        new_data = []
        duplicates = []

        with get_db() as db:
            for row in data:
                is_duplicate = False

                # 检查型号/编码是否重复（Excel 列名多为 product_code，库字段为 model_number）
                code = (row.get("product_code") or row.get("model_number") or "").strip()
                if code:
                    existing = db.query(Product).filter(Product.model_number == code).first()
                    if existing:
                        is_duplicate = True

                # 如果没有产品编码，检查产品名称 + 规格
                if not is_duplicate and row.get("product_name"):
                    query = db.query(Product).filter(Product.name == row["product_name"])
                    if row.get("specification"):
                        query = query.filter(Product.specification == row["specification"])
                    existing = query.first()
                    if existing:
                        is_duplicate = True

                if is_duplicate:
                    duplicates.append(row)
                else:
                    new_data.append(row)

        return new_data, duplicates

    def import_data(
        self,
        data: list[dict[str, Any]],
        skip_duplicates: bool = True,
        validate_before_import: bool = True,
        clean_data: bool = True,
        *,
        replace_attendance_detail_tagged: bool = False,
    ) -> dict[str, Any]:
        """
        导入产品数据

        Args:
            data: 数据列表
            skip_duplicates: 是否跳过重复项
            validate_before_import: 导入前是否验证
            clean_data: 是否清洗数据

        Returns:
            导入结果：
                - imported: 导入数量
                - skipped: 跳过数量
                - failed: 失败数量
                - details: 详细信息
        """
        result: dict[str, Any] = {
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "details": {"skipped_items": [], "failed_items": []},
        }

        try:
            if replace_attendance_detail_tagged:
                tag = "__from_attendance_detail__"
                with get_db() as db:
                    deleted = (
                        db.query(Product)
                        .filter(Product.description == tag)
                        .delete(synchronize_session=False)
                    )
                logger.info("已移除此前考勤明细导入的人员记录 %s 条", deleted)

            # 1. 清洗数据
            if clean_data:
                data = self.clean_data(data)

            # 2. 验证数据
            if validate_before_import:
                valid_data, invalid_data = self.validate_data(data)
                result["failed"] = len(invalid_data)
                result["details"]["failed_items"] = invalid_data
                data = valid_data

            # 3. 检查重复
            if skip_duplicates:
                new_data, duplicates = self.check_duplicates(data, skip_duplicates=True)
                result["skipped"] = len(duplicates)
                result["details"]["skipped_items"] = [
                    d.get("product_code") or d.get("product_name") for d in duplicates
                ]
                data = new_data

            # 4. 批量导入
            if not data:
                return result

            with get_db() as db:
                for row in data:
                    try:
                        product = Product(
                            model_number=(
                                row.get("product_code") or row.get("model_number") or None
                            )
                            or None,
                            name=row.get("product_name"),
                            specification=row.get("specification"),
                            price=float(row.get("unit_price", 0) or 0),
                            unit=row.get("unit", "个") or "个",
                            description=row.get("remark", "") or row.get("description", "") or "",
                            is_active=1,
                            created_at=datetime.now(),
                            updated_at=datetime.now(),
                        )
                        db.add(product)
                        result["imported"] += 1
                    except RECOVERABLE_ERRORS as e:
                        logger.error("导入产品失败：%s", e)
                        result["failed"] += 1
                        result["details"]["failed_items"].append({"data": row, "error": str(e)})

                db.commit()

            try:
                from app.infrastructure.mods.hooks import trigger

                trigger("product.imported", count=result["imported"], products=data)
            except RECOVERABLE_ERRORS as hook_err:
                logger.warning("Hook trigger failed: %s", hook_err)

            logger.info(
                "产品导入完成：成功%s, 跳过%s, 失败%s",
                result["imported"],
                result["skipped"],
                result["failed"],
            )

        except RECOVERABLE_ERRORS as e:
            logger.exception("导入产品数据失败：%s", e)
            result["error"] = str(e)

        return result

    def import_products_from_excel(self, file_path: str, unit_name: str) -> dict[str, Any]:
        """Read an Excel/CSV product sheet and pass normalized rows to ``import_data``."""
        try:
            import pandas as pd

            if str(file_path).lower().endswith(".csv"):
                frame = pd.read_csv(file_path, dtype=object)
            else:
                frame = pd.read_excel(file_path, dtype=object)
            aliases = {
                "产品编码": "product_code",
                "产品型号": "product_code",
                "型号": "product_code",
                "产品名称": "product_name",
                "名称": "product_name",
                "规格": "specification",
                "单价": "unit_price",
                "价格": "unit_price",
                "单位": "unit",
                "备注": "remark",
            }
            frame = frame.rename(
                columns={
                    column: aliases.get(str(column).strip(), str(column).strip())
                    for column in frame.columns
                }
            )
            frame = frame.where(frame.notna(), None)
            rows = [dict(row) for row in frame.to_dict(orient="records")]
            for row in rows:
                row.setdefault("unit", unit_name or "个")
            result = self.import_data(rows)
            result["success"] = not bool(result.get("error"))
            result["count"] = int(result.get("imported") or 0)
            return result
        except (OSError, ValueError, TypeError, ImportError) as exc:
            logger.exception("读取产品导入文件失败: %s", exc)
            return {"success": False, "message": f"读取导入文件失败：{exc}", "count": 0}

    def batch_add_products(self, products: list[dict[str, Any]], unit_name: str) -> dict[str, Any]:
        rows = [dict(item) for item in products]
        for row in rows:
            row.setdefault("unit", unit_name or "个")
        result = self.import_data(rows)
        result["success"] = not bool(result.get("error"))
        return result

    def validate_products(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        cleaned = self.clean_data([dict(item) for item in products])
        valid, invalid = self.validate_data(cleaned)
        return {
            "success": not invalid,
            "valid": valid,
            "invalid": invalid,
            "valid_count": len(valid),
            "invalid_count": len(invalid),
        }

    def get_import_history(self, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        from app.services.extract_log_service import ExtractLogService

        offset = max(0, page - 1) * max(1, per_page)
        items = ExtractLogService().get_logs(
            data_type="products", limit=max(1, per_page), offset=offset
        )
        return {"success": True, "items": items, "page": page, "per_page": per_page}


from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(ProductImportService, "app.services.product_import_service")
