"""Do not silently discard new CodeQL path-injection findings."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "codeql"
    / "strip_etl_dir_fd_path_injection_fps.py"
)
_SCRIPT_NS = runpy.run_path(str(_SCRIPT))
keep_result = _SCRIPT_NS["keep_result"]


def _finding(*, uri: str, line: int | None, rule: str = "py/path-injection") -> dict:
    region = {} if line is None else {"startLine": line}
    return {
        "ruleId": rule,
        "locations": [
            {"physicalLocation": {"artifactLocation": {"uri": uri}, "region": region}}
        ],
    }


_SHIPMENT = "FHD/app/application/shipment_excel_etl_security.py"
_EXCEL = "FHD/app/fastapi_routes/domains/excel/excel_extract.py"


@pytest.mark.parametrize(
    ("path", "line"),
    [(_SHIPMENT, 464), (_SHIPMENT, 807), (_SHIPMENT, 924),
     (_EXCEL, 65), (_EXCEL, 68), (_EXCEL, 125),
     (_EXCEL, 267), (_EXCEL, 269), (_EXCEL, 316)],
)
def test_only_explicitly_reviewed_sink_is_suppressed(path, line):
    assert keep_result(_finding(uri=path, line=line)) is False


@pytest.mark.parametrize("delta", [-40, -1, 1, 40, 100])
def test_nearby_new_sinks_are_preserved(delta):
    assert keep_result(_finding(uri=_SHIPMENT, line=464 + delta)) is True


def test_unknown_location_other_file_other_rule_are_preserved():
    assert keep_result(_finding(uri=_SHIPMENT, line=None)) is True
    assert keep_result(_finding(uri="FHD/app/application/other.py", line=464)) is True
    assert keep_result(_finding(uri=_SHIPMENT, line=464, rule="py/sql-injection")) is True
    assert keep_result({"ruleId": "py/path-injection", "locations": []}) is True


def test_related_location_cannot_hide_primary_sink():
    primary = _finding(uri="FHD/app/infrastructure/unreviewed.py", line=17)
    primary["locations"].append(_finding(uri=_SHIPMENT, line=464)["locations"][0])
    assert keep_result(primary) is True


def test_sarif_filter_preserves_new_findings(tmp_path):
    safe = _finding(uri=_SHIPMENT, line=464)
    unsafe = _finding(uri=_SHIPMENT, line=465)
    payload = {"runs": [{"results": [safe, unsafe]}]}
    sarif = tmp_path / "results.sarif"
    sarif.write_text(json.dumps(payload), encoding="utf-8")
    assert _SCRIPT_NS["main"]([str(_SCRIPT), str(sarif)]) == 0
    filtered = json.loads(sarif.read_text(encoding="utf-8"))
    assert filtered["runs"][0]["results"] == [unsafe]
