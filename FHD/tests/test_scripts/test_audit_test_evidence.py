"""Negative controls for audit JUnit accounting; no live services are required."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/audit_test_evidence.py"
_SPEC = importlib.util.spec_from_file_location("audit_test_evidence_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_REPORTS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_REPORTS)


def report(tmp_path, body, name="junit.xml"):
    path = tmp_path / name
    path.write_text(body)
    return path


def test_passed_cases_are_counted_from_records(tmp_path):
    path = report(tmp_path, '<testsuites><testsuite tests="2" skipped="0">'
                  '<testcase classname="a" name="one"/>'
                  '<testcase classname="a" name="two"/></testsuite></testsuites>')
    result = _REPORTS.inspect_reports([path], ("a::one",))
    assert result["status"] == "PASS"
    assert result["counts"] == {"passed": 2, "failed": 0, "errors": 0, "skipped": 0}


@pytest.mark.parametrize("outcome,status", [
    ('<skipped message="requires PostgreSQL"/>', "INCOMPLETE"),
    ('<failure message="assertion"/>', "FAIL"), ('<error message="collection"/>', "FAIL"),
])
def test_nonpassing_cases_cannot_be_green(tmp_path, outcome, status):
    path = report(tmp_path, f'<testsuite><testcase classname="a" name="one">'
                  f'{outcome}</testcase></testsuite>')
    assert _REPORTS.inspect_reports([path])["status"] == status


@pytest.mark.parametrize("body", [
    '<testsuites tests="100"/>', '<testsuite/>', '<not_junit/>', '<broken',
    '<testsuite tests="99"><testcase classname="a" name="one"/></testsuite>',
    '<testsuite failures="1"><testcase classname="a" name="one"/></testsuite>',
    '<testsuite tests="bad"><testcase classname="a" name="one"/></testsuite>',
    '<testsuite><testcase name="one"/></testsuite>',
    '<testsuite><testcase classname="a"/></testsuite>',
    '<testsuite><testcase classname="a" name="one"><skipped/></testcase></testsuite>',
    '<testsuite><testcase classname="a" name="one"><failure/><skipped message="x"/></testcase></testsuite>',
    '<testsuite><testcase classname="a" name="one"><rerunFailure/></testcase></testsuite>',
    '<!DOCTYPE foo [<!ENTITY x "value">]><testsuite/>',
])
def test_malformed_or_misleading_evidence_is_rejected(tmp_path, body):
    assert _REPORTS.inspect_reports([report(tmp_path, body)])["status"] == "FAIL"


def test_collection_skip_has_its_own_identity_and_reason(tmp_path):
    path = report(tmp_path, '<testsuite tests="1" skipped="1">'
                  '<testcase classname="" name="" file="tests/missing_module.py">'
                  '<skipped message="module absent"/></testcase></testsuite>')
    result = _REPORTS.inspect_reports([path])
    assert result["status"] == "INCOMPLETE"
    assert result["cases"][0]["id"] == "collection::tests/missing_module.py"
    assert result["counts"]["skipped"] == 1
    assert result["cases"][0]["skip_reason"] == "module absent"


def test_duplicate_reports_do_not_double_the_test_count(tmp_path):
    body = '<testsuite><testcase classname="a" name="one"/></testsuite>'
    paths = [report(tmp_path, body, "a.xml"), report(tmp_path, body, "b.xml")]
    result = _REPORTS.inspect_reports(paths)
    assert result["status"] == "FAIL"
    assert result["counts"]["passed"] == 1


def test_missing_required_case_is_not_inferred_from_totals(tmp_path):
    path = report(tmp_path, '<testsuite><testcase classname="a" name="one"/></testsuite>')
    assert _REPORTS.inspect_reports([path], ("a::two",))["status"] == "FAIL"


def test_skipped_required_case_is_rejected(tmp_path):
    path = report(tmp_path, '<testsuite><testcase classname="a" name="one">'
                  '<skipped message="platform"/></testcase></testsuite>')
    assert _REPORTS.inspect_reports([path], ("a::one",))["status"] == "FAIL"


def test_absent_empty_and_oversized_inputs_fail(tmp_path):
    assert _REPORTS.inspect_reports([])["status"] == "FAIL"
    assert _REPORTS.inspect_reports([tmp_path / "absent.xml"])["status"] == "FAIL"
    path = tmp_path / "oversized.xml"
    path.write_bytes(b" " * (_REPORTS.MAX_REPORT_BYTES + 1))
    assert _REPORTS.inspect_reports([path])["status"] == "FAIL"


def test_utf16_entity_document_is_rejected(tmp_path):
    path = tmp_path / "utf16.xml"
    path.write_bytes(('<?xml version="1.0" encoding="UTF-16"?>'
                      '<!DOCTYPE x [<!ENTITY y "value">]><testsuite/>').encode("utf-16"))
    assert _REPORTS.inspect_reports([path])["status"] == "FAIL"
