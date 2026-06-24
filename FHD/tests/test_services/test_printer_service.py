"""Behavior tests for app.services.printer_service.PrinterService.

These tests exercise the *real* printer selection / classification / routing
logic. Only the leaf IO collaborators ``PrinterUtils`` (system printer
enumeration + spool) and ``EnhancedPrinterUtils`` (automation spool) are mocked
— everything else (selection persistence, name resolution, document/label
guessing, classification, copy loops, branch routing) runs for real and is
asserted on concrete return values / observable call arguments.

``XCAGI_DATA_DIR`` is pointed at a per-test tmp dir so that
``get_app_data_dir()`` does not fall back to (and pollute) the repo root and so
that the on-disk ``printer_selection.json`` round-trips deterministically.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


class _PrinterServiceTestBase(unittest.TestCase):
    """Common scaffolding: isolated data dir + mocked leaf IO collaborators."""

    def setUp(self):
        # Isolate get_app_data_dir() so printer_selection.json lands in tmp,
        # never the repo root (which is the dev fallback of get_app_data_dir).
        self._tmpdir = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {"XCAGI_DATA_DIR": self._tmpdir.name})
        self._env.start()

        # Patch the two leaf IO collaborators at their use site in the service
        # module. Real classification / routing code runs against these mocks.
        self._p_printer = patch("app.services.printer_service.PrinterUtils")
        self._p_enhanced = patch("app.services.printer_service.EnhancedPrinterUtils")
        self.mock_printer_cls = self._p_printer.start()
        self.mock_enhanced_cls = self._p_enhanced.start()

        self.printer_utils = MagicMock()
        self.enhanced_utils = MagicMock()
        self.mock_printer_cls.return_value = self.printer_utils
        self.mock_enhanced_cls.return_value = self.enhanced_utils

    def tearDown(self):
        self._p_enhanced.stop()
        self._p_printer.stop()
        self._env.stop()
        self._tmpdir.cleanup()

    def _make_service(self):
        from app.services.printer_service import PrinterService

        return PrinterService()


# ---------------------------------------------------------------------------
# get_printers — exercises the REAL classify_printers pipeline
# ---------------------------------------------------------------------------
class TestGetPrinters(_PrinterServiceTestBase):
    def test_returns_printers_and_real_classification_summary(self):
        printers = [
            {"name": "HP LaserJet", "status": "就绪", "is_default": True},
            {"name": "TSC TTP-244", "status": "打印中", "is_default": False},
        ]
        self.printer_utils.get_available_printers.return_value = printers

        result = self._make_service().get_printers()

        # Top-level contract.
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["printers"], printers)
        self.printer_utils.get_available_printers.assert_called_once_with()

        # classify_printers ran for real: keyword guessing picked HP for docs
        # ("hp" keyword) and TSC for labels ("tsc"/"ttp" keyword).
        classified = result["classified"]
        self.assertEqual(classified["document_printer"]["name"], "HP LaserJet")
        self.assertEqual(classified["document_printer"]["status"], "就绪")
        self.assertTrue(classified["document_printer"]["is_connected"])
        self.assertEqual(classified["label_printer"]["name"], "TSC TTP-244")
        self.assertEqual(classified["label_printer"]["status"], "打印中")
        self.assertTrue(classified["label_printer"]["is_connected"])

        # Real summary aggregation.
        self.assertEqual(
            result["summary"],
            {
                "total_printers": 2,
                "document_printer_ready": True,
                "label_printer_ready": True,
                "all_ready": True,
            },
        )
        # No saved selection on disk yet -> selection echoes None.
        self.assertEqual(
            result["selection"],
            {"document_printer": None, "label_printer": None},
        )

    def test_empty_printer_list_marks_nothing_ready(self):
        self.printer_utils.get_available_printers.return_value = []

        result = self._make_service().get_printers()

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["printers"], [])
        # Real guessing returns None for an empty list -> not connected/ready.
        self.assertIsNone(result["classified"]["document_printer"]["name"])
        self.assertEqual(result["classified"]["document_printer"]["status"], "未连接")
        self.assertFalse(result["classified"]["document_printer"]["is_connected"])
        self.assertFalse(result["summary"]["all_ready"])
        self.assertEqual(result["summary"]["total_printers"], 0)

    def test_saved_selection_overrides_keyword_guess(self):
        printers = [
            {"name": "HP LaserJet", "status": "就绪"},
            {"name": "TSC TTP-244", "status": "就绪"},
            {"name": "Canon iR", "status": "就绪"},
        ]
        self.printer_utils.get_available_printers.return_value = printers
        service = self._make_service()
        # Persist an explicit selection that differs from the keyword guess.
        service.save_printer_selection("Canon iR", "TSC TTP-244")

        result = service.get_printers()

        classified = result["classified"]
        # document_printer honours the saved choice (Canon), not the first/HP guess.
        self.assertEqual(classified["document_printer"]["name"], "Canon iR")
        self.assertEqual(classified["label_printer"]["name"], "TSC TTP-244")
        self.assertEqual(
            result["selection"],
            {"document_printer": "Canon iR", "label_printer": "TSC TTP-244"},
        )

    def test_get_printers_recoverable_exception_returns_failure_envelope(self):
        self.printer_utils.get_available_printers.side_effect = RuntimeError("获取打印机失败")

        result = self._make_service().get_printers()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "获取打印机失败")
        self.assertEqual(result["printers"], [])
        # Failure envelope must NOT leak classification keys.
        self.assertNotIn("classified", result)


# ---------------------------------------------------------------------------
# get_default_printer — three branches
# ---------------------------------------------------------------------------
class TestGetDefaultPrinter(_PrinterServiceTestBase):
    def test_found(self):
        self.printer_utils.get_default_printer.return_value = "Default Printer"

        result = self._make_service().get_default_printer()

        self.assertEqual(result, {"success": True, "printer": "Default Printer"})

    def test_not_found_returns_specific_message(self):
        self.printer_utils.get_default_printer.return_value = None

        result = self._make_service().get_default_printer()

        self.assertEqual(result, {"success": False, "message": "未找到默认打印机"})
        self.assertNotIn("printer", result)

    def test_recoverable_exception_surfaces_message(self):
        self.printer_utils.get_default_printer.side_effect = RuntimeError("获取默认打印机异常")

        result = self._make_service().get_default_printer()

        self.assertEqual(result, {"success": False, "message": "获取默认打印机异常"})


# ---------------------------------------------------------------------------
# print_document — routing, name resolution, failure & automation
# ---------------------------------------------------------------------------
class TestPrintDocument(_PrinterServiceTestBase):
    def test_explicit_printer_routes_to_print_file_with_flags(self):
        self.printer_utils.print_file.return_value = {"success": True, "message": "打印成功"}

        result = self._make_service().print_document("test.pdf", printer_name="Test Printer")

        self.assertEqual(result, {"success": True, "message": "打印成功"})
        # Standard (non-automation) path is used and use_default_printer is forced off.
        self.printer_utils.print_file.assert_called_once_with(
            "test.pdf", "Test Printer", use_default_printer=False
        )
        self.enhanced_utils.print_file_enhanced.assert_not_called()

    def test_no_printer_name_resolves_via_real_document_printer(self):
        # No explicit name -> service must resolve through get_document_printer,
        # which enumerates printers and guesses. "Epson LQ" hits the doc keywords.
        self.printer_utils.get_available_printers.return_value = [
            {"name": "Epson LQ-590", "status": "就绪"},
        ]
        self.printer_utils.print_file.return_value = {"success": True, "message": "打印成功"}

        result = self._make_service().print_document("doc.pdf")

        self.assertTrue(result["success"])
        # The guessed printer name flowed through to the spool call.
        self.printer_utils.print_file.assert_called_once_with(
            "doc.pdf", "Epson LQ-590", use_default_printer=False
        )

    def test_falls_back_to_system_default_when_no_configured_printer(self):
        # get_document_printer returns None (no printers), so print_document
        # falls back to printer_utils.get_default_printer().
        self.printer_utils.get_available_printers.return_value = []
        self.printer_utils.get_default_printer.return_value = "System Default"
        self.printer_utils.print_file.return_value = {"success": True}

        result = self._make_service().print_document("doc.pdf")

        self.assertTrue(result["success"])
        self.printer_utils.print_file.assert_called_once_with(
            "doc.pdf", "System Default", use_default_printer=False
        )

    def test_no_printer_anywhere_returns_specific_error(self):
        self.printer_utils.get_available_printers.return_value = []
        self.printer_utils.get_default_printer.return_value = None

        result = self._make_service().print_document("test.pdf")

        self.assertEqual(
            result,
            {"success": False, "message": "未指定打印机且无法获取默认打印机"},
        )
        self.printer_utils.print_file.assert_not_called()

    def test_print_file_failure_envelope_is_passed_through(self):
        self.printer_utils.print_file.return_value = {"success": False, "message": "打印机失败"}

        result = self._make_service().print_document("test.pdf", printer_name="Test Printer")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "打印机失败")

    def test_automation_flag_routes_to_enhanced_spool(self):
        self.enhanced_utils.print_file_enhanced.return_value = {
            "success": True,
            "message": "增强打印成功",
        }

        result = self._make_service().print_document(
            "test.pdf", printer_name="Test Printer", use_automation=True
        )

        self.assertEqual(result, {"success": True, "message": "增强打印成功"})
        # Automation path used; standard spool untouched.
        self.enhanced_utils.print_file_enhanced.assert_called_once_with(
            "test.pdf", "Test Printer", use_automation=True
        )
        self.printer_utils.print_file.assert_not_called()

    def test_recoverable_exception_during_spool_returns_failure(self):
        self.printer_utils.print_file.side_effect = RuntimeError("打印机离线")

        result = self._make_service().print_document("test.pdf", printer_name="P")

        self.assertEqual(result, {"success": False, "message": "打印机离线"})


# ---------------------------------------------------------------------------
# print_label — copy loop, partial success, name resolution
# ---------------------------------------------------------------------------
class TestPrintLabel(_PrinterServiceTestBase):
    def test_single_copy_resolves_label_printer_and_reports_counts(self):
        # Real get_label_printer: "TSC" hits the label keyword set.
        self.printer_utils.get_available_printers.return_value = [
            {"name": "HP LaserJet", "status": "就绪"},
            {"name": "TSC TTP-244", "status": "就绪"},
        ]
        self.printer_utils.print_file.return_value = {"success": True, "message": "打印成功"}

        result = self._make_service().print_label("label.pdf")

        self.assertTrue(result["success"])
        self.assertEqual(result["printer"], "TSC TTP-244")
        self.assertEqual(result["copies"], 1)
        self.assertEqual(result["successful"], 1)
        self.assertEqual(result["message"], "标签打印完成: 1/1 成功")
        self.printer_utils.print_file.assert_called_once_with("label.pdf", "TSC TTP-244")
        # details carries per-copy breakdown.
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["copy"], 1)
        self.assertTrue(result["details"][0]["result"]["success"])

    def test_no_label_printer_available_returns_specific_error(self):
        self.printer_utils.get_available_printers.return_value = []

        result = self._make_service().print_label("label.pdf")

        self.assertEqual(result, {"success": False, "message": "未找到标签打印机"})
        self.printer_utils.print_file.assert_not_called()

    def test_multiple_copies_spool_once_per_copy(self):
        self.printer_utils.get_available_printers.return_value = [
            {"name": "TSC Label", "status": "就绪"},
        ]
        self.printer_utils.print_file.return_value = {"success": True, "message": "打印成功"}

        result = self._make_service().print_label("label.pdf", copies=3)

        self.assertTrue(result["success"])
        self.assertEqual(result["copies"], 3)
        self.assertEqual(result["successful"], 3)
        self.assertEqual(result["message"], "标签打印完成: 3/3 成功")
        self.assertEqual(self.printer_utils.print_file.call_count, 3)
        # Copy indices are 1-based and ordered.
        self.assertEqual([d["copy"] for d in result["details"]], [1, 2, 3])

    def test_explicit_printer_name_skips_resolution(self):
        self.printer_utils.print_file.return_value = {"success": True, "message": "打印成功"}

        result = self._make_service().print_label(
            "label.pdf", printer_name="Custom Label Printer", copies=2
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["printer"], "Custom Label Printer")
        self.assertEqual(result["copies"], 2)
        self.assertEqual(result["successful"], 2)
        # Explicit name -> no enumeration needed for resolution.
        self.printer_utils.get_available_printers.assert_not_called()

    def test_partial_success_counts_only_successful_copies(self):
        self.printer_utils.print_file.side_effect = [
            {"success": True, "message": "打印成功"},
            {"success": False, "message": "打印失败"},
            {"success": True, "message": "打印成功"},
        ]

        result = self._make_service().print_label(
            "label.pdf", printer_name="Label Printer", copies=3
        )

        # success is True because at least one copy succeeded.
        self.assertTrue(result["success"])
        self.assertEqual(result["successful"], 2)
        self.assertEqual(result["message"], "标签打印完成: 2/3 成功")
        # Per-copy detail reflects the mixed outcomes.
        self.assertEqual(
            [d["result"]["success"] for d in result["details"]],
            [True, False, True],
        )

    def test_all_copies_fail_marks_overall_failure(self):
        self.printer_utils.print_file.return_value = {"success": False, "message": "打印失败"}

        result = self._make_service().print_label(
            "label.pdf", printer_name="Label Printer", copies=2
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["successful"], 0)
        self.assertEqual(result["message"], "标签打印完成: 0/2 成功")

    def test_recoverable_exception_during_label_spool_returns_failure(self):
        self.printer_utils.print_file.side_effect = RuntimeError("标签打印机离线")

        result = self._make_service().print_label("label.pdf", printer_name="L")

        self.assertEqual(result, {"success": False, "message": "标签打印机离线"})


# ---------------------------------------------------------------------------
# test_printer — pass-through + exception envelope
# ---------------------------------------------------------------------------
class TestTestPrinter(_PrinterServiceTestBase):
    def test_passes_through_underlying_result_on_success(self):
        underlying = {
            "success": True,
            "available": True,
            "printer": "Test Printer",
            "status": "就绪",
        }
        self.printer_utils.test_printer.return_value = underlying

        result = self._make_service().test_printer("Test Printer")

        self.assertEqual(result, underlying)
        self.printer_utils.test_printer.assert_called_once_with("Test Printer")

    def test_passes_through_underlying_result_on_failure(self):
        underlying = {
            "success": False,
            "available": False,
            "printer": "Test Printer",
            "message": "打印机不可用",
        }
        self.printer_utils.test_printer.return_value = underlying

        result = self._make_service().test_printer("Test Printer")

        self.assertEqual(result, underlying)

    def test_recoverable_exception_builds_unavailable_envelope(self):
        self.printer_utils.test_printer.side_effect = RuntimeError("测试打印机异常")

        result = self._make_service().test_printer("Test Printer")

        self.assertEqual(
            result,
            {
                "success": False,
                "available": False,
                "printer": "Test Printer",
                "message": "测试打印机异常",
            },
        )


# ---------------------------------------------------------------------------
# validate_printer_separation — real doc/label resolution, all branches
# ---------------------------------------------------------------------------
class TestValidatePrinterSeparation(_PrinterServiceTestBase):
    def test_distinct_doc_and_label_printers_are_valid(self):
        # HP -> doc keyword, TSC -> label keyword: real resolution yields two
        # distinct printers.
        self.printer_utils.get_available_printers.return_value = [
            {"name": "HP LaserJet", "status": "就绪"},
            {"name": "TSC TTP-244", "status": "就绪"},
        ]

        result = self._make_service().validate_printer_separation()

        self.assertEqual(
            result,
            {
                "valid": True,
                "doc_printer": "HP LaserJet",
                "label_printer": "TSC TTP-244",
            },
        )

    def test_same_printer_for_doc_and_label_is_invalid(self):
        # A single printer with no keyword: guess falls back to first for docs
        # and last for labels -> the same single printer for both roles.
        self.printer_utils.get_available_printers.return_value = [
            {"name": "Generic Printer", "status": "就绪"},
        ]

        result = self._make_service().validate_printer_separation()

        self.assertFalse(result["valid"])
        self.assertEqual(result["message"], "发货单打印机和标签打印机相同")
        self.assertEqual(result["doc_printer"], "Generic Printer")
        self.assertEqual(result["label_printer"], "Generic Printer")

    def test_no_printers_cannot_identify_either_role(self):
        self.printer_utils.get_available_printers.return_value = []

        result = self._make_service().validate_printer_separation()

        self.assertFalse(result["valid"])
        self.assertEqual(result["message"], "无法识别发货单或标签打印机")
        self.assertIsNone(result["doc_printer"])
        self.assertIsNone(result["label_printer"])

    def test_recoverable_exception_returns_failure_with_message(self):
        self.printer_utils.get_available_printers.side_effect = RuntimeError("验证异常")

        result = self._make_service().validate_printer_separation()

        self.assertEqual(result, {"valid": False, "message": "验证异常"})


# ---------------------------------------------------------------------------
# Selection persistence + name resolution + guessing (previously untested)
# ---------------------------------------------------------------------------
class TestSelectionAndResolution(_PrinterServiceTestBase):
    def test_save_then_get_selection_round_trips_through_disk(self):
        service = self._make_service()

        saved = service.save_printer_selection("  HP LaserJet  ", "TSC TTP")

        # Names are trimmed and a success envelope is returned.
        self.assertTrue(saved["success"])
        self.assertEqual(saved["message"], "打印机选择已保存")
        self.assertEqual(
            saved["selection"],
            {"document_printer": "HP LaserJet", "label_printer": "TSC TTP"},
        )

        # A fresh service instance reads the persisted file back.
        reloaded = self._make_service().get_printer_selection()
        self.assertEqual(
            reloaded,
            {"document_printer": "HP LaserJet", "label_printer": "TSC TTP"},
        )

    def test_blank_selection_persists_as_none(self):
        service = self._make_service()

        saved = service.save_printer_selection("   ", "")

        self.assertEqual(
            saved["selection"],
            {"document_printer": None, "label_printer": None},
        )
        self.assertEqual(
            service.get_printer_selection(),
            {"document_printer": None, "label_printer": None},
        )

    def test_get_selection_with_no_file_returns_none_pair(self):
        # No save has happened: _load_selection sees a missing file.
        result = self._make_service().get_printer_selection()

        self.assertEqual(
            result,
            {"document_printer": None, "label_printer": None},
        )

    def test_corrupt_selection_file_is_tolerated_as_empty(self):
        service = self._make_service()
        # Write garbage into the on-disk selection file.
        with open(service._selection_file, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json")

        # JSONDecodeError is in RECOVERABLE_ERRORS -> _load_selection returns {}.
        self.assertEqual(
            service.get_printer_selection(),
            {"document_printer": None, "label_printer": None},
        )

    def test_resolve_name_exact_then_case_insensitive_then_miss(self):
        from app.services.printer_service import PrinterService

        printers = [{"name": "HP LaserJet"}, {"name": "TSC TTP-244"}]

        # Exact match wins.
        self.assertEqual(PrinterService._resolve_name("HP LaserJet", printers), "HP LaserJet")
        # Case-insensitive fallback returns the canonical stored name.
        self.assertEqual(PrinterService._resolve_name("hp laserjet", printers), "HP LaserJet")
        # Unknown name resolves to None.
        self.assertIsNone(PrinterService._resolve_name("Brother", printers))
        # Blank target resolves to None.
        self.assertIsNone(PrinterService._resolve_name("   ", printers))

    def test_guess_document_printer_prefers_keyword_else_first(self):
        from app.services.printer_service import PrinterService

        # Keyword "epson" wins over position.
        keyword_hit = [{"name": "Brother HL"}, {"name": "Epson LQ"}]
        self.assertEqual(PrinterService._guess_document_printer(keyword_hit), "Epson LQ")
        # No keyword -> first printer.
        no_keyword = [{"name": "AlphaPrint"}, {"name": "BetaPrint"}]
        self.assertEqual(PrinterService._guess_document_printer(no_keyword), "AlphaPrint")
        # Empty list -> None.
        self.assertIsNone(PrinterService._guess_document_printer([]))

    def test_guess_label_printer_prefers_keyword_else_last(self):
        from app.services.printer_service import PrinterService

        # Keyword "zebra" wins over position.
        keyword_hit = [{"name": "Zebra GK420"}, {"name": "Plain Printer"}]
        self.assertEqual(PrinterService._guess_label_printer(keyword_hit), "Zebra GK420")
        # No keyword -> last printer.
        no_keyword = [{"name": "AlphaPrint"}, {"name": "BetaPrint"}]
        self.assertEqual(PrinterService._guess_label_printer(no_keyword), "BetaPrint")
        # Empty list -> None.
        self.assertIsNone(PrinterService._guess_label_printer([]))

    def test_classify_status_unknown_when_name_absent_from_list(self):
        # A saved selection names a printer that is not in the live list:
        # _resolve_name fails to match -> guessing kicks in, and status_of for
        # a guessed name present in the list reports its real status.
        printers = [{"name": "HP LaserJet", "status": "缺纸"}]
        service = self._make_service()
        service.save_printer_selection("Ghost Printer", "Ghost Label")

        classified = service.classify_printers(printers)

        # Saved names did not resolve; fell back to the single live printer.
        self.assertEqual(classified["classified"]["document_printer"]["name"], "HP LaserJet")
        self.assertEqual(classified["classified"]["document_printer"]["status"], "缺纸")
        # The original (unresolved) selection is still echoed back verbatim.
        self.assertEqual(
            classified["selection"],
            {"document_printer": "Ghost Printer", "label_printer": "Ghost Label"},
        )


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------
class TestModuleLevelHelpers(_PrinterServiceTestBase):
    def test_get_printers_helper_returns_only_the_list(self):
        import app.services.printer_service as mod

        printers = [{"name": "HP LaserJet", "status": "就绪"}]
        with patch.object(mod.printer_service, "get_printers") as m:
            m.return_value = {"success": True, "printers": printers, "count": 1}
            self.assertEqual(mod.get_printers(), printers)

    def test_get_printers_helper_returns_empty_on_failure_envelope(self):
        import app.services.printer_service as mod

        with patch.object(mod.printer_service, "get_printers") as m:
            m.return_value = {"success": False, "message": "boom"}
            # Failure envelope has no "printers" key -> wrapper defaults to [].
            self.assertEqual(mod.get_printers(), [])

    def test_validate_printer_separation_helper_delegates(self):
        import app.services.printer_service as mod

        sentinel = {"valid": True, "doc_printer": "A", "label_printer": "B"}
        with patch.object(mod.printer_service, "validate_printer_separation") as m:
            m.return_value = sentinel
            self.assertIs(mod.validate_printer_separation(), sentinel)


if __name__ == "__main__":
    unittest.main()
