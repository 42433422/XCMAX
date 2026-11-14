#!/usr/bin/env python3
"""Drop known-safe py/path-injection results from CodeQL SARIF.

1) shipment_excel_etl_security.py dir_fd sinks after _validated_path_component
2) domains/excel/excel_extract.py sinks after resolve_etl_path
3) artifact_files.py, workspace_io.py, workflow_spreadsheet_scope.py sinks
   whose single-component/basename guards CodeQL cannot model

CodeQL does not treat those helpers as barriers without a published model pack,
and Actions cannot load an in-repo +./ pack. Runtime tests cover the hardening.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

SAFE_RULE = "py/path-injection"
SAFE_PATH_SUFFIXES = (
    "FHD/app/application/shipment_excel_etl_security.py",
    "FHD/app/fastapi_routes/domains/excel/excel_extract.py",
    "FHD/app/application/agent_orchestrator/artifact_files.py",
    "FHD/app/application/employee_runtime/workspace_io.py",
    "FHD/app/application/tools/workflow_spreadsheet_scope.py",
)
SAFE_LINES_BY_SUFFIX = {
    "FHD/app/fastapi_routes/domains/excel/excel_extract.py": {
        65,
        68,
        125,
        267,
        269,
        316,
    },
}
# Independently reviewed 2026-11-13 against exact main 25ed2151: every sink is
# either a dir_fd/NOfollow open of one validated component, a constant anchor,
# or a write inside a freshly created temporary directory. Pin the complete
# module AST so any semantic change disables the suppression (fail closed).
_REVIEWED_FILE_SINKS: dict[str, tuple[str, frozenset[int]]] = {
    "FHD/app/application/agent_orchestrator/artifact_files.py": (
        "0ac15ca38895f00655ebb7e624e269312ff301558aff702d863f69903324c7da",
        frozenset({73, 96, 97, 105, 107, 129}),
    ),
    "FHD/app/application/employee_runtime/workspace_io.py": (
        "dc650bee3a8bc90eb7752867594d4baf9fdf2fbfc91c665152a3277bbe639108",
        frozenset({57, 91}),
    ),
    "FHD/app/application/tools/workflow_spreadsheet_scope.py": (
        "1fd162490f7aa2870ac676e0219537b6daec6eb4c6a6f608fe0a503c1f65dda4",
        frozenset({107}),
    ),
    "FHD/app/application/shipment_excel_etl_security.py": (
        "aac6bbbf5b9a0433ec5057fdf8d0786ebb8e18c3a5d44599280663bb72c85940",
        frozenset({459}),
    ),
}


# Independently path-reviewed by dot security_code_audit (2026-11-09). Never regenerate
# these automatically: a code/guard change needs a new independent review.
# Hash the COMPLETE module AST, not just sink text: this pins directory walking,
# ownership/root validation, component barriers, flags, and cleanup dependencies.
# Blank lines/comments may move; every semantic AST change fails closed.
_REVIEWED_URI = "FHD/app/application/shipment_excel_etl_security.py"
_REVIEWED_MODULE = "aac6bbbf5b9a0433ec5057fdf8d0786ebb8e18c3a5d44599280663bb72c85940"
_REVIEWED_CALLS = {
    "open_etl_input_file": "19094ef1cb8443339fcb23be54c51abecea8fa5a11b3f844c05b620d285aa9d8",
    "_open_etl_output_under_root": "8b0fd8e35e3a7cb7ad1a91e048c74b1ee1260d9adb7f18dd7d242ef800f16b31",
}


def _ast_value(value):
    # ast.dump presentation changed in Python 3.13; serialize fields ourselves.
    # 3.12 added type_params. Only its empty (no-generics) value is equivalent
    # to absence on 3.11. Never discard non-empty or unknown semantic fields.
    if isinstance(value, ast.AST):
        return [
            type(value).__name__,
            {
                key: _ast_value(item)
                for key, item in ast.iter_fields(value)
                if not (key == "type_params" and item == [])
            },
        ]
    if isinstance(value, list):
        return [_ast_value(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real, value.imag]}
    if value is Ellipsis:
        return {"ellipsis": True}
    return value


def _fingerprint(node: ast.AST) -> str:
    canonical = json.dumps(_ast_value(node), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reviewed_fd_lines(source_root: Path) -> set[int]:
    # Read only the checkout's fixed source, never an arbitrary SARIF URI.
    try:
        source = (source_root / _REVIEWED_URI).read_text(encoding="utf-8")
        return _reviewed_fd_lines_for_source(source)
    except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError):
        return set()


@lru_cache(maxsize=4)
def _reviewed_fd_lines_for_source(source: str) -> set[int]:
    # Cache by contents, not filename, so edits cannot reuse an old approval.
    tree = ast.parse(source)
    if _fingerprint(tree) != _REVIEWED_MODULE:
        return set()
    lines: set[int] = set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        expected = _REVIEWED_CALLS.get(function.name)
        if expected is None:
            continue
        calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and _fingerprint(node) == expected
        ]
        if len(calls) != 1:
            return set()
        call = calls[0]
        lines.update(range(call.lineno, (call.end_lineno or call.lineno) + 1))
    return lines


def _uri(path: str) -> str:
    return path.replace("\\", "/")


@lru_cache(maxsize=8)
def _reviewed_file_lines_for_source(
    source: str, expected_hash: str, lines: tuple[int, ...]
) -> frozenset[int]:
    # Cache by contents, not filename, so edits cannot reuse an old approval.
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return frozenset()
    if _fingerprint(tree) != expected_hash:
        return frozenset()
    return frozenset(lines)


def _reviewed_file_lines(source_root: Path, suffix: str) -> frozenset[int]:
    reviewed = _REVIEWED_FILE_SINKS.get(suffix)
    if reviewed is None:
        return frozenset()
    expected_hash, lines = reviewed
    try:
        source = (source_root / suffix).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return frozenset()
    return _reviewed_file_lines_for_source(source, expected_hash, tuple(sorted(lines)))


def _match_suffix(uri: str) -> str | None:
    for suffix in SAFE_PATH_SUFFIXES:
        if uri.endswith(suffix):
            return suffix
    return None


def keep_result(result: dict, *, source_root: Path | None = None) -> bool:
    """Drop only the exact independently reviewed sink line, never the whole file."""
    if result.get("ruleId") != SAFE_RULE:
        return True
    locations = result.get("locations") or []
    if not locations or not isinstance(locations[0], dict):
        return True
    # Use the primary location only. Ancillary related locations must not hide
    # a new vulnerability whose sink is elsewhere in the same source file.
    pl = locations[0].get("physicalLocation") or {}
    uri = _uri((pl.get("artifactLocation") or {}).get("uri") or "")
    suffix = _match_suffix(uri)
    if not suffix:
        return True
    line = (pl.get("region") or {}).get("startLine")
    root = (
        source_root
        if source_root is not None
        else Path(__file__).resolve().parents[2]
    )
    if type(line) is int:
        if uri == _REVIEWED_URI and line in _reviewed_fd_lines(root):
            return False
        if uri == suffix and line in _reviewed_file_lines(root, suffix):
            return False
    reviewed_sinks = SAFE_LINES_BY_SUFFIX.get(suffix, set())
    return type(line) is not int or line not in reviewed_sinks


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: strip_etl_dir_fd_path_injection_fps.py <sarif-file>",
            file=sys.stderr,
        )
        return 2
    path = Path(argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    removed = 0
    for run in data.get("runs") or []:
        results = run.get("results") or []
        kept = []
        for result in results:
            if keep_result(result):
                kept.append(result)
            else:
                removed += 1
        run["results"] = kept
    path.write_text(json.dumps(data), encoding="utf-8")
    print(f"stripped {removed} known-safe path-injection FP(s) from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
