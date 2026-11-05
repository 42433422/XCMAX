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
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": region}}],
    }


_SHIPMENT = "FHD/app/application/shipment_excel_etl_security.py"
_EXCEL = "FHD/app/fastapi_routes/domains/excel/excel_extract.py"


@pytest.mark.parametrize(
    ("path", "line"),
    [
        (_EXCEL, 65),
        (_EXCEL, 68),
        (_EXCEL, 125),
        (_EXCEL, 267),
        (_EXCEL, 269),
        (_EXCEL, 316),
    ],
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
    safe = _finding(uri=_EXCEL, line=65)
    unsafe = _finding(uri=_SHIPMENT, line=465)
    payload = {"runs": [{"results": [safe, unsafe]}]}
    sarif = tmp_path / "results.sarif"
    sarif.write_text(json.dumps(payload), encoding="utf-8")
    assert _SCRIPT_NS["main"]([str(_SCRIPT), str(sarif)]) == 0
    filtered = json.loads(sarif.read_text(encoding="utf-8"))
    assert filtered["runs"][0]["results"] == [unsafe]


# The two fd findings are tied to source semantics, never to yesterday's lines.
_SOURCE = (_SCRIPT.parents[2] / _SHIPMENT).read_text(encoding="utf-8")


def _fd_line(source, function_name):
    import ast

    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    method = "open" if function_name == "open_etl_input_file" else "rename"
    return next(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr == method
    )


def _source_tree(tmp_path, source):
    destination = tmp_path / _SHIPMENT
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("function", ["open_etl_input_file", "open_etl_output_file"])
def test_reviewed_fd_sinks_survive_only_nonsemantic_line_drift(tmp_path, function):
    source = "# harmless line drift\n\n" + _SOURCE
    root = _source_tree(tmp_path, source)
    finding = _finding(uri=_SHIPMENT, line=_fd_line(source, function))
    assert keep_result(finding, source_root=root) is False


@pytest.mark.parametrize("function", ["open_etl_input_file", "open_etl_output_file"])
@pytest.mark.parametrize(
    "old,new",
    [
        ("os.O_NOFOLLOW", "0"),
        ('re.fullmatch(r"[^/\\\\]+", name)', "True"),
        ("dir_fd=parent_fd", "dir_fd=other_fd"),
        ("src_dir_fd=parent_fd", "src_dir_fd=other_fd"),
        ("stat.S_ISREG(os.fstat(descriptor).st_mode)", "True"),
        ("component != value", "False"),
        ('return _safe_under_roots(str(file_path or ""), roots)', "return Path(file_path)"),
        ("os.open(os.sep, directory_flags)", "os.open(os.sep, os.O_RDONLY)"),
    ],
)
def test_guard_or_sink_mutation_preserves_findings(tmp_path, function, old, new):
    assert old in _SOURCE, "mutation must actually change reviewed code"
    source = _SOURCE.replace(old, new)
    root = _source_tree(tmp_path, source)
    assert (
        keep_result(_finding(uri=_SHIPMENT, line=_fd_line(source, function)), source_root=root)
        is True
    )


def test_new_neighbor_sink_and_original_both_fail_closed(tmp_path):
    marker = "descriptor = os.open(name, flags, dir_fd=parent_fd)"
    source = _SOURCE.replace(marker, "os.open(name)\n            " + marker)
    assert source != _SOURCE
    root = _source_tree(tmp_path, source)
    line = _fd_line(source, "open_etl_input_file")
    assert keep_result(_finding(uri=_SHIPMENT, line=line), source_root=root)
    assert keep_result(_finding(uri=_SHIPMENT, line=line + 1), source_root=root)


@pytest.mark.parametrize("kind", ["missing", "syntax", "encoding"])
def test_missing_or_unparseable_source_preserves_fd_findings(tmp_path, kind):
    if kind != "missing":
        root = _source_tree(tmp_path, "def invalid(:" if kind == "syntax" else "")
        if kind == "encoding":
            (root / _SHIPMENT).write_bytes(b"\xff")
    assert keep_result(
        _finding(uri=_SHIPMENT, line=_fd_line(_SOURCE, "open_etl_input_file")), source_root=tmp_path
    )


def test_fd_matching_requires_exact_uri_rule_and_primary_location():
    line = _fd_line(_SOURCE, "open_etl_input_file")
    for uri in ["other/" + _SHIPMENT, "../" + _SHIPMENT, "file:///" + _SHIPMENT]:
        assert keep_result(_finding(uri=uri, line=line))
    assert keep_result(_finding(uri=_SHIPMENT, line=line, rule="py/other"))
    primary = _finding(uri=_SHIPMENT, line=1)
    safe = _finding(uri=_SHIPMENT, line=line)["locations"][0]
    primary["locations"].append(safe)
    primary["relatedLocations"] = [safe]
    assert keep_result(primary)


def test_source_change_cannot_reuse_cached_approval(tmp_path):
    root = _source_tree(tmp_path, _SOURCE)
    finding = _finding(uri=_SHIPMENT, line=_fd_line(_SOURCE, "open_etl_input_file"))
    assert not keep_result(finding, source_root=root)
    _source_tree(tmp_path, _SOURCE.replace("os.O_NOFOLLOW", "0"))
    assert keep_result(finding, source_root=root)


def test_retired_shipment_line_numbers_never_approve_unreviewed_code(tmp_path):
    root = _source_tree(tmp_path, "# no reviewed sinks here\n")
    for line in (464, 807, 924):
        assert keep_result(_finding(uri=_SHIPMENT, line=line), source_root=root)


def test_ast_fingerprint_normalizes_only_empty_new_type_parameters():
    import ast
    import copy

    node = ast.parse("def f(): pass").body[0]
    legacy = copy.deepcopy(node)
    legacy._fields = tuple(field for field in legacy._fields if field != "type_params")
    modern = copy.deepcopy(node)
    modern._fields = (*legacy._fields, "type_params")
    modern.type_params = []
    fingerprint = _SCRIPT_NS["_fingerprint"]
    assert fingerprint(legacy) == fingerprint(modern)
    modern.type_params = [ast.Name(id="T", ctx=ast.Load())]
    assert fingerprint(legacy) != fingerprint(modern)


def test_stable_fingerprint_does_not_depend_on_ast_dump(monkeypatch):
    import ast

    monkeypatch.setattr(ast, "dump", lambda *a, **k: "different interpreter formatting")
    assert _SCRIPT_NS["_fingerprint"](ast.parse(_SOURCE)) == _SCRIPT_NS["_REVIEWED_MODULE"]
