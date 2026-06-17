"""Tests for app.tasks.shipment_tasks — Celery tasks for shipment operations."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import MaxRetriesExceededError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_self():
    """Build a mock self object for bound Celery tasks.

    When calling bound Celery tasks directly, the task instance is passed as
    ``self`` automatically.  We patch ``retry`` on the actual task object
    and use the real Celery ``MaxRetriesExceededError`` for catch compatibility.
    """
    s = MagicMock()
    s.MaxRetriesExceededError = MaxRetriesExceededError
    return s


# ---------------------------------------------------------------------------
# generate_shipment_order
# ---------------------------------------------------------------------------


class TestGenerateShipmentOrder:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import generate_shipment_order

        mock_svc = MagicMock()
        mock_svc.generate_shipment_document.return_value = {
            "success": True,
            "doc_name": "doc.pdf",
            "file_path": "/tmp/doc.pdf",
        }
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch.object(generate_shipment_order, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_shipment_order(
                "TestCo", [{"product_name": "P1", "quantity": 5}], "2026-01-01"
            )
        assert result["success"] is True
        assert result["doc_name"] == "doc.pdf"

    def test_retry_on_recoverable_error(self, mock_self):
        from app.tasks.shipment_tasks import generate_shipment_order

        mock_svc = MagicMock()
        mock_svc.generate_shipment_document.side_effect = RuntimeError("db down")
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch.object(generate_shipment_order, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_shipment_order("TestCo", [{"product_name": "P1", "quantity": 5}])
        assert result["success"] is False
        assert "db down" in result["message"]

    def test_value_error_is_recoverable(self, mock_self):
        from app.tasks.shipment_tasks import generate_shipment_order

        mock_svc = MagicMock()
        mock_svc.generate_shipment_document.side_effect = ValueError("bad data")
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch.object(generate_shipment_order, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_shipment_order("TestCo", [{"product_name": "P1", "quantity": 5}])
        assert result["success"] is False


# ---------------------------------------------------------------------------
# generate_batch_shipment_orders
# ---------------------------------------------------------------------------


class TestGenerateBatchShipmentOrders:
    def test_all_succeed(self, mock_self):
        from app.tasks.shipment_tasks import generate_batch_shipment_orders

        orders = [
            {"unit_name": "Co1", "products": [{"product_name": "P1", "quantity": 1}]},
            {"unit_name": "Co2", "products": [{"product_name": "P2", "quantity": 2}]},
        ]
        with (
            patch(
                "app.tasks.shipment_tasks.generate_shipment_order",
                return_value={"success": True, "doc_name": "doc.pdf"},
            ),
            patch.object(
                generate_batch_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = generate_batch_shipment_orders(orders)
        assert result["success"] is True
        assert result["succeeded"] == 2
        assert result["failed"] == 0

    def test_mixed_results(self, mock_self):
        from app.tasks.shipment_tasks import generate_batch_shipment_orders

        orders = [
            {"unit_name": "Co1", "products": []},
            {"unit_name": "Co2", "products": []},
        ]
        with (
            patch(
                "app.tasks.shipment_tasks.generate_shipment_order",
                side_effect=[
                    {"success": True},
                    {"success": False, "message": "error"},
                ],
            ),
            patch.object(
                generate_batch_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = generate_batch_shipment_orders(orders)
        assert result["success"] is False
        assert result["succeeded"] == 1
        assert result["failed"] == 1

    def test_retry_on_outer_error(self, mock_self):
        from app.tasks.shipment_tasks import generate_batch_shipment_orders

        with (
            patch(
                "app.tasks.shipment_tasks.generate_shipment_order",
                side_effect=RuntimeError("fatal"),
            ),
            patch.object(
                generate_batch_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = generate_batch_shipment_orders([{"unit_name": "Co1", "products": []}])
        assert result["success"] is False

    def test_inner_recoverable_error_counted_as_failed(self, mock_self):
        from app.tasks.shipment_tasks import generate_batch_shipment_orders

        with (
            patch(
                "app.tasks.shipment_tasks.generate_shipment_order",
                side_effect=ValueError("bad"),
            ),
            patch.object(
                generate_batch_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = generate_batch_shipment_orders([{"unit_name": "Co1", "products": []}])
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# print_shipment_document
# ---------------------------------------------------------------------------


class TestPrintShipmentDocument:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import print_shipment_document

        with (
            patch("os.path.exists", return_value=True),
            patch.object(print_shipment_document, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = print_shipment_document("/tmp/doc.pdf", "HP", 2)
        assert result["success"] is True
        assert result["file_path"] == "/tmp/doc.pdf"

    def test_file_not_found(self, mock_self):
        from app.tasks.shipment_tasks import print_shipment_document

        with (
            patch("os.path.exists", return_value=False),
            patch.object(print_shipment_document, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = print_shipment_document("/tmp/missing.pdf")
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_retry_on_error(self, mock_self):
        from app.tasks.shipment_tasks import print_shipment_document

        with (
            patch("os.path.exists", side_effect=RuntimeError("io error")),
            patch.object(print_shipment_document, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = print_shipment_document("/tmp/doc.pdf")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# cleanup_old_shipment_documents  (not bind=True, no self)
# ---------------------------------------------------------------------------


class TestCleanupOldShipmentDocuments:
    def test_dir_not_exists(self):
        from app.tasks.shipment_tasks import cleanup_old_shipment_documents

        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/fake_data"),
            patch("os.path.exists", return_value=False),
        ):
            result = cleanup_old_shipment_documents(90)
        assert result == 0

    def test_cleans_old_files(self):
        from app.tasks.shipment_tasks import cleanup_old_shipment_documents

        old_mtime = (datetime.now() - timedelta(days=100)).timestamp()
        recent_mtime = (datetime.now() - timedelta(days=1)).timestamp()

        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/fake_data"),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("os.path.isfile", return_value=True),
            patch("os.listdir", return_value=["old.pdf", "recent.pdf"]),
            patch("os.path.getmtime", side_effect=[old_mtime, recent_mtime]),
            patch("os.path.join", side_effect=lambda d, f: f"{d}/{f}"),
            patch("os.remove") as mock_remove,
        ):
            result = cleanup_old_shipment_documents(90)
        assert result == 1
        mock_remove.assert_called_once()

    def test_remove_failure_continues(self):
        from app.tasks.shipment_tasks import cleanup_old_shipment_documents

        old_mtime = (datetime.now() - timedelta(days=100)).timestamp()

        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/fake_data"),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("os.path.isfile", return_value=True),
            patch("os.listdir", return_value=["old.pdf"]),
            patch("os.path.getmtime", return_value=old_mtime),
            patch("os.path.join", side_effect=lambda d, f: f"{d}/{f}"),
            patch("os.remove", side_effect=PermissionError("denied")),
        ):
            result = cleanup_old_shipment_documents(90)
        assert result == 0

    def test_outer_exception_returns_zero(self):
        from app.tasks.shipment_tasks import cleanup_old_shipment_documents

        with patch("app.utils.path_utils.get_app_data_dir", side_effect=RuntimeError("fail")):
            result = cleanup_old_shipment_documents(90)
        assert result == 0

    def test_skips_non_files(self):
        from app.tasks.shipment_tasks import cleanup_old_shipment_documents

        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/fake_data"),
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("os.listdir", return_value=["subdir"]),
            patch("os.path.isfile", return_value=False),
            patch("os.path.join", side_effect=lambda d, f: f"{d}/{f}"),
        ):
            result = cleanup_old_shipment_documents(90)
        assert result == 0


# ---------------------------------------------------------------------------
# export_shipment_records_task
# ---------------------------------------------------------------------------


class TestExportShipmentRecordsTask:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import export_shipment_records_task

        mock_svc = MagicMock()
        mock_svc.export_shipment_records.return_value = {
            "success": True,
            "file_path": "/tmp/export.xlsx",
            "count": 10,
        }
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch.object(
                export_shipment_records_task, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = export_shipment_records_task(unit_name="TestCo")
        assert result["success"] is True

    def test_retry_on_error(self, mock_self):
        from app.tasks.shipment_tasks import export_shipment_records_task

        mock_svc = MagicMock()
        mock_svc.export_shipment_records.side_effect = RuntimeError("fail")
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch.object(
                export_shipment_records_task, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = export_shipment_records_task()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# import_products_batch_task
# ---------------------------------------------------------------------------


class TestImportProductsBatchTask:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import import_products_batch_task

        mock_svc = MagicMock()
        mock_svc.add_product.return_value = {"success": True}
        with (
            patch("app.services.get_products_service", return_value=mock_svc),
            patch.object(import_products_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = import_products_batch_task(
                [{"name": "P1", "unit_price": 10}],
                "TestCo",
            )
        assert result["success"] is True
        assert result["imported"] == 1

    def test_skip_duplicates(self, mock_self):
        from app.tasks.shipment_tasks import import_products_batch_task

        mock_svc = MagicMock()
        mock_svc.add_product.return_value = {"success": False, "message": "产品已存在"}
        with (
            patch("app.services.get_products_service", return_value=mock_svc),
            patch.object(import_products_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = import_products_batch_task(
                [{"name": "P1"}],
                "TestCo",
                skip_duplicates=True,
            )
        assert result["skipped_duplicates"] == 1

    def test_item_error(self, mock_self):
        from app.tasks.shipment_tasks import import_products_batch_task

        mock_svc = MagicMock()
        mock_svc.add_product.side_effect = RuntimeError("db error")
        with (
            patch("app.services.get_products_service", return_value=mock_svc),
            patch.object(import_products_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = import_products_batch_task(
                [{"name": "P1"}],
                "TestCo",
            )
        assert result["failed"] == 1

    def test_retry_on_outer_error(self, mock_self):
        from app.tasks.shipment_tasks import import_products_batch_task

        with (
            patch("app.services.get_products_service", side_effect=RuntimeError("fatal")),
            patch.object(import_products_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = import_products_batch_task([{"name": "P1"}], "TestCo")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# generate_labels_batch_task
# ---------------------------------------------------------------------------


class TestGenerateLabelsBatchTask:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import generate_labels_batch_task

        mock_svc = MagicMock()
        mock_svc.generate_label.return_value = {"success": True}
        with (
            patch("app.services.get_printer_service", return_value=mock_svc),
            patch.object(generate_labels_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_labels_batch_task(
                [{"product_name": "P1", "quantity": 2}],
            )
        assert result["success"] is True
        assert result["generated"] == 1

    def test_label_error_continues(self, mock_self):
        from app.tasks.shipment_tasks import generate_labels_batch_task

        mock_svc = MagicMock()
        mock_svc.generate_label.side_effect = RuntimeError("printer error")
        with (
            patch("app.services.get_printer_service", return_value=mock_svc),
            patch.object(generate_labels_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_labels_batch_task(
                [{"product_name": "P1"}],
            )
        assert result["generated"] == 0
        assert len(result["results"]) == 1

    def test_retry_on_outer_error(self, mock_self):
        from app.tasks.shipment_tasks import generate_labels_batch_task

        with (
            patch("app.services.get_printer_service", side_effect=RuntimeError("fatal")),
            patch.object(generate_labels_batch_task, "retry", side_effect=MaxRetriesExceededError),
        ):
            result = generate_labels_batch_task([{"product_name": "P1"}])
        assert result["success"] is False


# ---------------------------------------------------------------------------
# generate_parallel_shipment_orders
# ---------------------------------------------------------------------------


class TestGenerateParallelShipmentOrders:
    def test_success(self, mock_self):
        from app.tasks.shipment_tasks import generate_parallel_shipment_orders

        mock_result = MagicMock()
        mock_result.id = "group-123"
        mock_task_result = MagicMock()
        mock_task_result.id = "task-1"
        mock_result.results = [mock_task_result]

        with (
            patch("app.tasks.shipment_tasks.generate_shipment_order") as mock_gen,
            patch("celery.group") as mock_group_cls,
            patch.object(
                generate_parallel_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            mock_group_inst = MagicMock()
            mock_group_inst.apply_async.return_value = mock_result
            mock_group_cls.return_value = mock_group_inst

            result = generate_parallel_shipment_orders([{"unit_name": "Co1", "products": []}])
        assert result["success"] is True
        assert result["total"] == 1

    def test_error(self, mock_self):
        from app.tasks.shipment_tasks import generate_parallel_shipment_orders

        with (
            patch("celery.group", side_effect=RuntimeError("broker down")),
            patch.object(
                generate_parallel_shipment_orders, "retry", side_effect=MaxRetriesExceededError
            ),
        ):
            result = generate_parallel_shipment_orders([{"unit_name": "Co1", "products": []}])
        assert result["success"] is False
