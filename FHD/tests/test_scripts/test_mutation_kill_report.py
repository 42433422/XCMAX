"""mutation_kill_report.parse_results — mutmut 2.x / 3.x 格式。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "mutation_kill_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("mutation_kill_report", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_mutmut3_progress_line():
    mod = _load()
    out = "Running\n⠿ 90/90  🎉 67 🫥 0  ⏰ 0  🤔 0  🙁 23  🔇 0  🧙 0\n60.0 mutations/second\n"
    c = mod.parse_results(out)
    assert c["killed"] == 67
    assert c["survived"] == 23
    assert c["timeout"] == 0
    assert abs(mod.compute_kill_rate(c) - 67 / 90) < 1e-9


def test_parse_mutmut3_results_lines():
    mod = _load()
    out = "\n".join(
        [
            "    app.di.registry.x__mutmut_1: killed",
            "    app.di.registry.x__mutmut_2: survived",
            "    app.di.registry.x__mutmut_3: timeout",
            "    app.di.registry.x__mutmut_4: no_tests",
        ]
    )
    c = mod.parse_results(out)
    assert c == {"killed": 1, "survived": 1, "timeout": 1, "no_tests": 1}


def test_parse_legacy_killed_survived():
    mod = _load()
    out = "Killed 🎉 (10)\nSurvived 🙁 (2)\nTimeout ⏰ (1)\n"
    c = mod.parse_results(out)
    assert c["killed"] == 10
    assert c["survived"] == 2
    assert c["timeout"] == 1


def test_progress_includes_skipped_and_type_check_results_in_denominator():
    mod = _load()
    counts = mod.parse_results("100/100 🎉 70 🫥 0 ⏰ 0 🤔 0 🙁 0 🔇 20 🧙 10\n")
    assert mod.compute_kill_rate(counts) == 0.7
    assert counts["no_tests"] == 20
    assert counts["timeout"] == 10


def test_uncovered_mutants_cannot_inflate_gate_score(tmp_path, monkeypatch):
    mod = _load()
    log = tmp_path / "mutations.log"
    log.write_text("268/268  🎉 94 🫥 168  ⏰ 0  🤔 0  🙁 6  🔇 0  🧙 0\n")
    monkeypatch.setattr(
        "sys.argv",
        ["mutation_kill_report", "--threshold", "80", "--from-file", str(log), "--dry-run"],
    )
    assert (
        abs(
            mod.compute_kill_rate({"killed": 94, "survived": 6, "timeout": 0, "no_tests": 168})
            - 94 / 268
        )
        < 1e-9
    )
    assert mod.main() == 1
