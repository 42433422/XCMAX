"""
发货单相关 Celery 任务模块

包含大批量发货单生成、打印等异步任务。
"""

import logging
import os
from typing import Any, cast

from app.extensions import celery_app
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def generate_shipment_order(
    self, unit_name: str, products: list[dict[str, Any]], date: str | None = None
) -> dict[str, Any]:
    """
    生成发货单（异步任务）

    Args:
        unit_name: 单位名称
        products: 产品列表，每个产品包含：
            - product_name: 产品名称
            - quantity: 数量
            - price: 价格（可选）
        date: 发货日期（可选，默认今天）

    Returns:
        结果字典：
            - success: 是否成功
            - doc_name: 文档名称
            - file_path: 文件路径
            - message: 响应消息
    """
    try:
        logger.info("开始生成发货单：%s, 产品数量：%s", unit_name, len(products))

        # 调用服务层生成发货单
        from app.bootstrap import get_shipment_app_service

        app_service = get_shipment_app_service()
        result = app_service.generate_shipment_document(
            unit_name=unit_name, products=products, date=date
        )

        logger.info("发货单生成完成：%s", result)
        return cast("dict[str, Any]", result)

    except RECOVERABLE_ERRORS as e:
        logger.exception("生成发货单失败：%s", e)
        try:
            self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error("生成发货单达到最大重试次数")
            return {
                "success": False,
                "message": f"生成失败：{str(e)}",
                "doc_name": None,
                "file_path": None,
            }


@celery_app.task(bind=True, max_retries=3)
def generate_batch_shipment_orders(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
    """
    批量生成发货单

    Args:
        orders: 订单列表，每个订单包含：
            - unit_name: 单位名称
            - products: 产品列表
            - date: 发货日期（可选）

    Returns:
        结果字典：
            - success: 是否成功
            - total: 总订单数
            - succeeded: 成功数量
            - failed: 失败数量
            - results: 每个订单的结果
    """
    try:
        logger.info("开始批量生成发货单，订单数：%s", len(orders))

        results = []
        succeeded = 0
        failed = 0

        for order in orders:
            try:
                result = generate_shipment_order(
                    unit_name=order.get("unit_name"),
                    products=order.get("products", []),
                    date=order.get("date"),
                )
                results.append(result)
                if result.get("success"):
                    succeeded += 1
                else:
                    failed += 1
            except RECOVERABLE_ERRORS as e:
                logger.exception("生成单个发货单失败：%s", e)
                failed += 1
                results.append({"success": False, "message": str(e)})

        logger.info("批量生成完成：成功 %s, 失败 %s", succeeded, failed)

        return {
            "success": failed == 0,
            "total": len(orders),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    except RECOVERABLE_ERRORS as e:
        logger.exception("批量生成发货单失败：%s", e)
        try:
            self.retry(exc=e, countdown=120)
        except self.MaxRetriesExceededError:
            logger.error("批量生成发货单达到最大重试次数")
            return {
                "success": False,
                "message": f"批量生成失败：{str(e)}",
                "total": len(orders),
                "succeeded": 0,
                "failed": len(orders),
                "results": [],
            }


@celery_app.task(bind=True, max_retries=3)
def print_shipment_document(
    self, file_path: str, printer_name: str | None = None, copies: int = 1
) -> dict[str, Any]:
    """
    打印发货单

    Args:
        file_path: 文件路径
        printer_name: 打印机名称（可选，使用默认打印机）
        copies: 打印份数

    Returns:
        结果字典：
            - success: 是否成功
            - message: 响应消息
    """
    try:
        logger.info("开始打印发货单：%s, 打印机：%s, 份数：%s", file_path, printer_name, copies)

        # 1. 验证文件存在
        import os

        if not os.path.exists(file_path):
            return {"success": False, "message": f"文件不存在：{file_path}"}

        result = {
            "success": True,
            "message": "发货单已标记为已打印，请在客户端完成物理打印",
            "file_path": file_path,
            "printed_at": None,
        }

        logger.info("打印完成：%s", result)
        return result

    except RECOVERABLE_ERRORS as e:
        logger.exception("打印发货单失败：%s", e)
        try:
            self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error("打印发货单达到最大重试次数")
            return {"success": False, "message": f"打印失败：{str(e)}"}


@celery_app.task
def cleanup_old_shipment_documents(days: int = 90) -> int:
    """
    清理旧的发货单文件

    Args:
        days: 保留天数

    Returns:
        清理的文件数量
    """
    try:
        logger.info("开始清理 %s 天前的发货单文件", days)

        from datetime import datetime, timedelta

        from app.utils.path_utils import get_app_data_dir

        output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")

        if not os.path.exists(output_dir):
            logger.info("发货单输出目录不存在：%s", output_dir)
            return 0

        cutoff_date = datetime.now() - timedelta(days=days)
        cleaned_count = 0

        for filename in os.listdir(output_dir):
            file_path = os.path.join(output_dir, filename)

            if not os.path.isfile(file_path):
                continue

            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))

            if file_mtime < cutoff_date:
                try:
                    os.remove(file_path)
                    cleaned_count += 1
                    logger.info("已删除旧发货单：%s", filename)
                except RECOVERABLE_ERRORS as e:
                    logger.warning("删除文件失败 %s: %s", filename, e)

        logger.info("清理完成，共清理 %s 个文件", cleaned_count)
        return cleaned_count

    except RECOVERABLE_ERRORS as e:
        logger.exception("清理旧文件失败：%s", e)
        return 0


@celery_app.task(bind=True, max_retries=3, queue="normal")
def export_shipment_records_task(
    self,
    unit_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """
    导出出货记录（异步任务）

    Args:
        unit_name: 单位名称（可选）
        start_date: 开始日期（可选）
        end_date: 结束日期（可选）

    Returns:
        结果字典：
            - success: 是否成功
            - file_path: 文件路径
            - filename: 文件名
            - count: 导出记录数
    """
    try:
        logger.info("开始异步导出出货记录：unit=%s, start=%s, end=%s", unit_name, start_date, end_date)

        from app.bootstrap import get_shipment_app_service

        app_service = get_shipment_app_service()
        result = app_service.export_shipment_records(unit_name=unit_name)

        logger.info("导出完成：%s", result)
        return cast("dict[str, Any]", result)

    except RECOVERABLE_ERRORS as e:
        logger.exception("导出出货记录失败：%s", e)
        try:
            self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error("导出出货记录达到最大重试次数")
            return {
                "success": False,
                "message": f"导出失败：{str(e)}",
                "file_path": None,
                "filename": None,
                "count": 0,
            }


@celery_app.task(bind=True, max_retries=3, queue="normal")
def import_products_batch_task(
    self, products_data: list[dict[str, Any]], unit_name: str, skip_duplicates: bool = True
) -> dict[str, Any]:
    """
    批量导入产品（异步任务）

    Args:
        products_data: 产品数据列表
        unit_name: 购买单位名称
        skip_duplicates: 是否跳过重复

    Returns:
        结果字典：
            - success: 是否成功
            - imported: 导入数量
            - skipped_duplicates: 跳过重复数量
            - failed: 失败数量
    """
    try:
        logger.info("开始异步批量导入产品：unit=%s, 数量=%s", unit_name, len(products_data))

        from app.services import get_products_service

        service = get_products_service()

        imported = 0
        skipped = 0
        failed = 0
        failed_items = []

        batch_size = 100
        for i in range(0, len(products_data), batch_size):
            batch = products_data[i : i + batch_size]
            for item in batch:
                try:
                    item["unit"] = unit_name
                    result = service.add_product(item)
                    if result.get("success"):
                        imported += 1
                    elif skip_duplicates and "已存在" in str(result.get("message", "")):
                        skipped += 1
                    else:
                        failed += 1
                        failed_items.append(item)
                except RECOVERABLE_ERRORS as item_err:
                    logger.warning("导入单个产品失败：%s", item_err)
                    failed += 1
                    failed_items.append(item)

        logger.info("批量导入完成：成功=%s, 跳过=%s, 失败=%s", imported, skipped, failed)
        return {
            "success": failed == 0,
            "imported": imported,
            "skipped_duplicates": skipped,
            "failed": failed,
            "failed_items": failed_items[:10],
        }

    except RECOVERABLE_ERRORS as e:
        logger.exception("批量导入产品失败：%s", e)
        try:
            self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error("批量导入产品达到最大重试次数")
            return {
                "success": False,
                "message": f"导入失败：{str(e)}",
                "imported": 0,
                "skipped_duplicates": 0,
                "failed": len(products_data),
                "failed_items": [],
            }


@celery_app.task(bind=True, max_retries=3, queue="normal")
def generate_labels_batch_task(self, labels: list[dict[str, Any]]) -> dict[str, Any]:
    """
    批量生成标签（异步任务）

    Args:
        labels: 标签列表，每个标签包含：
            - product_name: 产品名称
            - model_number: 型号（可选）
            - specification: 规格（可选）
            - quantity: 数量

    Returns:
        结果字典：
            - success: 是否成功
            - generated: 生成数量
            - file_path: 文件路径
    """
    try:
        logger.info("开始异步批量生成标签：数量=%s", len(labels))

        from app.services import get_printer_service

        service = get_printer_service()

        generated = 0
        results = []

        for label in labels:
            try:
                result = service.generate_label(
                    product_name=label.get("product_name"),
                    model_number=label.get("model_number"),
                    specification=label.get("specification"),
                    quantity=label.get("quantity", 1),
                )
                if result.get("success"):
                    generated += 1
                results.append(result)
            except RECOVERABLE_ERRORS as label_err:
                logger.warning("生成单个标签失败：%s", label_err)
                results.append({"success": False, "message": str(label_err)})

        logger.info("批量生成标签完成：成功=%s", generated)
        return {
            "success": generated > 0,
            "generated": generated,
            "total": len(labels),
            "results": results[:20],
        }

    except RECOVERABLE_ERRORS as e:
        logger.exception("批量生成标签失败：%s", e)
        try:
            self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error("批量生成标签达到最大重试次数")
            return {
                "success": False,
                "message": f"生成失败：{str(e)}",
                "generated": 0,
                "total": len(labels),
                "results": [],
            }


@celery_app.task(bind=True, max_retries=3, queue="urgent")
def generate_parallel_shipment_orders(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
    """
    并行生成批量发货单（使用 group 并行执行）

    Args:
        orders: 订单列表

    Returns:
        结果字典：
            - success: 是否成功
            - total: 总订单数
            - succeeded: 成功数量
            - failed: 失败数量
            - task_ids: 任务 ID 列表
    """
    try:
        from celery import group

        logger.info("开始并行生成发货单，订单数：%s", len(orders))

        job = group(
            generate_shipment_order.s(
                order.get("unit_name"), order.get("products", []), order.get("date")
            )
            for order in orders
        )

        result = job.apply_async()
        task_ids = result.results

        logger.info("并行任务已提交，task_ids: %s", [t.id for t in task_ids])

        return {
            "success": True,
            "total": len(orders),
            "task_ids": [t.id for t in task_ids],
            "group_id": result.id,
            "message": "并行任务已提交",
        }

    except RECOVERABLE_ERRORS as e:
        logger.exception("并行生成发货单失败：%s", e)
        return {
            "success": False,
            "message": f"任务提交失败：{str(e)}",
            "total": len(orders),
            "succeeded": 0,
            "failed": len(orders),
        }
