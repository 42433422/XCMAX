"""Only assertion failures may contribute to mutation kills."""

import json

import pytest

from scripts.dev.mutation_isolated import classify


@pytest.mark.parametrize(
    "code,log,expected",
    [
        (0, "1 passed", "survived"),
        (1, "FAILED test_rule - AssertionError\n1 failed", "killed"),
        (1, "ERROR at teardown of test_rule\n1 error", "error"),
        (1, "ResourceWarning: unclosed scandir iterator", "error"),
        (1, "Traceback (most recent call last):", "error"),
        (0, "PytestUnraisableExceptionWarning: cleanup", "error"),
        (2, "collection interrupted", "error"),
        (3, "INTERNALERROR", "error"),
        (5, "no tests ran", "error"),
        (-9, "", "error"),
    ],
)
def test_distinguishes_test_failures_from_runner_failures(code, log, expected):
    assert classify(code, log) == expected


@pytest.mark.parametrize("baseline_fails", [False, True])
def test_real_process_accounting_and_baseline_gate(tmp_path, monkeypatch, baseline_fails):
    from scripts.dev import mutation_isolated

    root = tmp_path / "mutants"
    for folder in ["app/di", "app/contexts", "tests/test_di", "tests/test_contexts"]:
        (root / folder).mkdir(parents=True)
    names = ["app.di.sample__mutmut_1", "app.di.sample__mutmut_2"]
    (root / "app/di/sample.meta").write_text(json.dumps({"exit_code_by_key": dict.fromkeys(names)}))
    test = root / "tests/test_di/test_sample.py"
    test.write_text(
        "import os\ndef test_sample():\n"
        + (
            "    assert False\n"
            if baseline_fails
            else "    assert os.environ.get('MUTANT_UNDER_TEST') != 'app.di.sample__mutmut_1'\n"
        )
    )
    (root / "mutmut-stats.json").write_text(
        json.dumps(
            {
                "tests_by_mangled_function_name": {
                    "app.di.sample": ["tests/test_di/test_sample.py::test_sample"]
                }
            }
        )
    )
    output = tmp_path / "evidence"
    monkeypatch.setattr(
        "sys.argv",
        ["isolated", "--mutants", str(root), "--output", str(output), "--threshold", "50"],
    )
    result = mutation_isolated.main()
    if baseline_fails:
        assert result == 2
        assert not (output / "report.json").exists()
        assert not (output / "results.jsonl").exists()
    else:
        assert result == 0
        report = json.loads((output / "report.json").read_text())
        assert report["counts"] == {
            "killed": 1,
            "survived": 1,
            "error": 0,
            "timeout": 0,
            "no_tests": 0,
        }
        rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
        assert {r["name"] for r in rows} == set(names)
        assert all((output / r["log"]).is_file() for r in rows)
