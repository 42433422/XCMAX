"""A12: a tool that did not run provides no verification credit."""

from vibe_coding.agent.tools.runner import ToolReport, ToolRunner


class Adapter:
    name = "required-test"
    languages = ("python",)

    def __init__(self, *, available=True, passed=True):
        self.available = available
        self.passed = passed
        self.calls = 0

    def is_available(self):
        return self.available

    def run(self, *args, **kwargs):
        self.calls += 1
        return ToolReport(tool=self.name, passed=self.passed)


def runner(adapters, **kwargs):
    # The driver is not exercised by these adapters; do not start external tools.
    return ToolRunner(adapters=adapters, sandbox=object(), **kwargs)


def test_missing_required_tool_is_unavailable_not_passed(tmp_path):
    absent = Adapter(available=False)
    subject = runner([absent])
    report = subject.run_all(tmp_path)[0]
    assert not report.passed and not report.executed
    assert report.status == "UNAVAILABLE"
    assert report.to_dict()["status"] == "UNAVAILABLE"
    assert report.exit_code == -1
    assert not subject.all_passed(tmp_path)
    assert absent.calls == 0


def test_success_and_failure_are_executed(tmp_path):
    reports = runner([Adapter(), Adapter(passed=False)]).run_all(tmp_path)
    assert [r.status for r in reports] == ["PASS", "FAIL"]
    assert all(r.executed for r in reports)


def test_successful_suite_still_passes(tmp_path):
    assert runner([Adapter(), Adapter()]).all_passed(tmp_path)


def test_empty_configuration_cannot_verify_a_patch(tmp_path):
    subject = runner([])
    assert len(subject.adapters) == 0
    reports = subject.run_all(tmp_path)
    assert reports and all(not r.passed for r in reports)
    assert not subject.all_passed(tmp_path)


def test_fail_fast_stops_after_unavailable(tmp_path):
    absent, later = Adapter(available=False), Adapter()
    reports = runner([absent, later], fail_fast=True).run_all(tmp_path)
    assert len(reports) == 1 and later.calls == 0


def test_non_fail_fast_preserves_other_diagnostics(tmp_path):
    later = Adapter()
    reports = runner([Adapter(available=False), later]).run_all(tmp_path)
    assert [r.status for r in reports] == ["UNAVAILABLE", "PASS"]
    assert later.calls == 1


def test_availability_exception_does_not_abort_collection(tmp_path):
    class Broken(Adapter):
        def is_available(self):
            raise OSError("availability probe failed")

    later = Adapter()
    reports = runner([Broken(), later]).run_all(tmp_path)
    assert not reports[0].passed and "OSError" in reports[0].error
    assert later.calls == 1


def test_inconsistent_unexecuted_report_cannot_claim_success(tmp_path):
    class Skipped(Adapter):
        def run(self, *args, **kwargs):
            report = ToolReport(tool=self.name, passed=True, executed=False)
            report.passed = True
            return report

    reports = runner([Skipped()]).run_all(tmp_path)
    assert not reports[0].passed and reports[0].status == "UNAVAILABLE"
