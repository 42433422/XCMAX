"""Read-only Calc verification of a frozen workbook, never a second writer.

LibreOffice owns formula evaluation. Its isolated profile forces a hard OOXML
recalculation (Office.Calc/Formula/Load/OOXMLRecalcMode=0); openpyxl only compares
the input cells with the resulting workbook. The produced copy is not delivered
or substituted for the original artifact.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import posixpath
import re
import shutil
import subprocess
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from xml.etree.ElementTree import Element, ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from openpyxl import load_workbook
from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import TokenizerError
from openpyxl.styles.numbers import BUILTIN_FORMATS, BUILTIN_FORMATS_MAX_SIZE
from openpyxl.utils.exceptions import InvalidFileException

from app.application.employee_runtime.continuity_tool_wait import (
    ProcessLimits,
    ProcessLimitsExceeded,
    ProcessLimitsUnavailable,
)
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.utils.path_io.path_utils import get_app_data_dir
from app.utils.process_lock import exclusive_file_lock

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_MAX_FORMULAS = 10_000
_MAX_CELLS = 500_000
_MAX_BYTES = 64 * 1024 * 1024
_MAX_SAMPLES = 64
_PROCESS_LIMITS = ProcessLimits(
    cpu_seconds=60, address_space_bytes=2 * 1024**3, file_size_bytes=_MAX_BYTES
)
# These functions can resolve unowned files, fetch URLs, or call external code.
# A private profile alone is not a filesystem/network sandbox for INDIRECT.
_EXTERNAL_FUNCTIONS = frozenset(
    {
        "CALL",
        "DDE",
        "EXEC",
        "EVALUATE",
        "IMAGE",
        "INDIRECT",
        "REGISTER.ID",
        "RTD",
        "WEBSERVICE",
        "HYPERLINK",
        "STOCKHISTORY",
        "PY",
    }
)
_PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
 <item oor:path="/org.openoffice.Office.Calc/Formula/Load">
  <prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Calc/Content/Update">
  <prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
  <prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
  <prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
  <prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Calc/Filter/Import/VBA">
  <prop oor:name="Executable" oor:op="fuse"><value>false</value></prop>
 </item>
</oor:items>
"""


class _Unavailable(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@contextmanager
def _engine_slot(deadline: float):
    # One Calc process per shared host data directory, across worker processes.
    # Lock waiting consumes the original invocation budget, including version lookup.
    with ExitStack() as acquired:
        try:
            acquired.enter_context(
                exclusive_file_lock(
                    Path(get_app_data_dir()) / "agent-runtime" / "workbook-recalculation.lock",
                    blocking=True,
                    timeout=max(0, deadline - time.monotonic()),
                    reject_symlink=True,
                )
            )
        except TimeoutError:
            raise
        except OSError as exc:
            raise _Unavailable("formula_recalculation_concurrency_unavailable") from exc
        yield


def _engine_path() -> str | None:
    # Reuse the host's existing LibreOffice setting, never a tool parameter.
    configured = os.environ.get("LIBREOFFICE_PATH", "").strip()
    if configured:
        return shutil.which(configured)
    return (
        shutil.which("soffice")
        or shutil.which("libreoffice")
        or (
            "/Applications/LibreOffice.app/Contents/MacOS/soffice"
            if Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").is_file()
            else None
        )
    )


def _safe_formula(formula: str) -> None:
    if len(formula) > 8192:
        raise _Unavailable("formula_recalculation_formula_too_large")
    for token in Tokenizer(formula if formula.startswith("=") else "=" + formula).items:
        if token.type == "FUNC" and token.subtype == "OPEN":
            name = token.value[:-1].upper().removeprefix("_XLFN.").removeprefix("_XLWS.")
            if name in _EXTERNAL_FUNCTIONS or name.startswith(
                ("CUBE", "COM.", "ORG.", "_XLL.", "_XLUDF.")
            ):
                raise _Unavailable("formula_recalculation_external_function")
        if (
            token.type == "OPERAND"
            and token.subtype == "RANGE"
            and (
                any(marker in token.value for marker in ("\\", "/", "|"))
                or ("[" in token.value and "!" in token.value)
            )
        ):
            raise _Unavailable("formula_recalculation_external_reference")


def _inspect_package(content: bytes, suffix: str) -> None:
    if suffix != ".xlsx":
        raise _Unavailable("formula_recalculation_macro_or_format_unsupported")
    with ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if not {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"} <= set(
            names
        ):
            raise _Unavailable("formula_recalculation_package_invalid")
        if (
            len(names) > 4096
            or len(names) != len(set(names))
            or sum(item.file_size for item in archive.infolist()) > _MAX_BYTES
        ):
            raise _Unavailable("formula_recalculation_package_limit")
        for name in names:
            lower = name.lower()
            if any(
                marker in lower
                for marker in (
                    "vbaproject",
                    "macrosheets/",
                    "externallinks/",
                    "connections.xml",
                    "querytables/",
                    "embeddings/",
                    "activex/",
                )
            ):
                raise _Unavailable("formula_recalculation_active_content")
            if not lower.endswith((".xml", ".rels")):
                continue
            root = fromstring(archive.read(name))
            for node in root.iter():
                if (
                    node.get("TargetMode", "").lower() == "external"
                    or "macroenabled" in node.get("ContentType", "").lower()
                    or "vbaproject" in node.get("ContentType", "").lower()
                    or "macrosheet" in node.get("ContentType", "").lower()
                    or any(
                        name in node.get("Type", "").lower()
                        for name in ("macrosheet", "vbaproject")
                    )
                ):
                    raise _Unavailable("formula_recalculation_active_content")
                tag = node.tag.rsplit("}", 1)[-1]
                if (
                    tag
                    in {
                        "f",
                        "formula",
                        "formula1",
                        "formula2",
                        "definedName",
                        "calculatedColumnFormula",
                        "totalsRowFormula",
                    }
                    and node.text
                ):
                    if node.get("function") in {"1", "true"} or node.get("vbProcedure") in {
                        "1",
                        "true",
                    }:
                        raise _Unavailable("formula_recalculation_active_content")
                    _safe_formula(node.text)
                if tag == "calcPr" and node.get("iterate") in {"1", "true"}:
                    raise _Unavailable("formula_recalculation_iterative_unsupported")
        # openpyxl silently skips a missing worksheet member. Such a package
        # must not become an apparently valid workbook with zero formulas.
        _sheet_parts(archive)


def _sheet_parts(archive: ZipFile) -> list[tuple[str, str]]:
    relationships = {
        node.get("Id"): node.get("Target", "")
        for node in fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    }
    parts = []
    for sheet in fromstring(archive.read("xl/workbook.xml")).findall(f"{_NS}sheets/{_NS}sheet"):
        target = relationships.get(sheet.get(_RID))
        name = sheet.get("name")
        if not target or not name:
            raise _Unavailable("formula_recalculation_package_invalid")
        path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        if path not in archive.namelist():
            raise _Unavailable("formula_recalculation_package_invalid")
        parts.append((name, path))
    if not parts:
        raise _Unavailable("formula_recalculation_package_invalid")
    return parts


def _cells(content: bytes) -> tuple[list[str], dict, dict]:
    try:
        book = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    except KeyError as exc:
        # openpyxl uses KeyError for missing OOXML ZIP members/relationships.
        # Keep this data-boundary exception local, not a catch over our own code.
        raise _Unavailable("formula_recalculation_package_invalid") from exc
    try:
        formulas, literals = {}, {}
        if sum(len(item._cells) for item in book.worksheets) > _MAX_CELLS:
            raise _Unavailable("formula_recalculation_cell_limit")
        for sheet in book.worksheets:
            for cell in sheet._cells.values():
                key = sheet.title, cell.coordinate
                if cell.data_type == "f":
                    if not isinstance(cell.value, str):
                        raise _Unavailable("formula_recalculation_array_unsupported")
                    formulas[key] = cell.value
                elif cell.value is not None:
                    literals[key] = (cell.data_type, cell.value)
        if len(formulas) > _MAX_FORMULAS:
            raise _Unavailable("formula_recalculation_formula_limit")
        return book.sheetnames, formulas, literals
    finally:
        book.close()


def _formula_semantics(formula: str) -> str:
    # Calc serializes logical constants as zero-argument calls. Tokenize with
    # openpyxl so text, cell/name references and calls with arguments stay exact.
    tokens, values, index = Tokenizer(formula).items, [], 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token.type == "FUNC"
            and token.subtype == "OPEN"
            and token.value.upper() in {"TRUE(", "FALSE("}
            and index + 1 < len(tokens)
            and (tokens[index + 1].type, tokens[index + 1].subtype) == ("FUNC", "CLOSE")
        ):
            values.append(token.value[:-1].upper())
            index += 2
        else:
            values.append(
                token.value.upper()
                if (token.type, token.subtype) == ("OPERAND", "LOGICAL")
                else token.value
            )
            index += 1
    return "=" + "".join(values)


def _table_semantics(node: Element) -> tuple:
    """Keep ordered columns, formulas and metadata without ZIP identity or XML spelling."""
    tag = node.tag.removeprefix(_NS)
    defaults = {
        "table": {
            "headerRowCount": "1",
            "totalsRowCount": "0",
            "totalsRowShown": "1",
            "tableType": "worksheet",
        },
        "tableColumn": {"totalsRowFunction": "none"},
        "calculatedColumnFormula": {"array": "0"},
        "totalsRowFormula": {"array": "0"},
    }
    attributes = {**defaults.get(tag, {}), **node.attrib}
    if tag == "table":
        attributes.pop("id", None)  # Package-local IDs can change during conversion.
        attributes.setdefault("name", attributes.get("displayName", ""))
        attributes["ref"] = attributes.get("ref", "").replace("$", "").upper()
        for key in ("headerRowCount", "totalsRowCount"):
            attributes[key] = str(int(attributes[key]))
    elif tag == "tableColumns":
        attributes.pop("count", None)  # The actual ordered children define the columns.
    for key in ("totalsRowShown", "insertRow", "insertRowShift", "published", "array"):
        if attributes.get(key) in {"true", "1"}:
            attributes[key] = "1"
        elif attributes.get(key) in {"false", "0"}:
            attributes[key] = "0"
    text = node.text or ""
    return (
        node.tag,
        tuple(sorted(attributes.items())),
        text if text.strip() else "",
        tuple(_table_semantics(child) for child in node),
    )


def _table_context(archive: ZipFile) -> tuple:
    """Resolve table ownership through each worksheet's own relationships."""
    members = set(archive.namelist())
    tables = []
    for sheet_name, sheet_path in _sheet_parts(archive):
        sheet = fromstring(archive.read(sheet_path))
        parts = sheet.findall(f"{_NS}tableParts/{_NS}tablePart")
        if not parts:
            continue
        directory = posixpath.dirname(sheet_path)
        rels_path = posixpath.join(directory, "_rels", posixpath.basename(sheet_path) + ".rels")
        if rels_path not in members:
            raise _Unavailable("formula_recalculation_package_invalid")
        relationships = {}
        for relationship in fromstring(archive.read(rels_path)):
            identity = relationship.get("Id")
            if not identity or identity in relationships:
                raise _Unavailable("formula_recalculation_package_invalid")
            relationships[identity] = relationship
        for part in parts:
            binding = relationships.get(part.get(_RID, ""))
            if binding is None or binding.get("Type") != (
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
            ):
                raise _Unavailable("formula_recalculation_package_invalid")
            target = binding.get("Target", "")
            path = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else posixpath.join(directory, target)
            )
            if not target or path not in members:
                raise _Unavailable("formula_recalculation_package_invalid")
            table = fromstring(archive.read(path))
            if table.tag != f"{_NS}table":
                raise _Unavailable("formula_recalculation_package_invalid")
            tables.append((sheet_name, _table_semantics(table)))
    return tuple(sorted(tables))


def _display_context(content: bytes, *, full_precision: bool) -> tuple:
    """Bind hidden rows and precision-as-displayed inputs using openpyxl's styles."""
    book = load_workbook(io.BytesIO(content), data_only=False, keep_links=False)
    try:
        visibility, formats = [], []
        # openpyxl's published stubs omit its shared style catalogue and backing arrays.
        cell_styles: list[Any] = cast(Any, book)._cell_styles
        number_formats: list[str] = cast(Any, book)._number_formats

        def number_format(style: Any) -> str:
            # Compare resolved format codes, not converter-local style/format IDs.
            style = style if style is not None else cell_styles[0]
            index: int = style.numFmtId
            if index < BUILTIN_FORMATS_MAX_SIZE:
                return BUILTIN_FORMATS.get(index, f"builtin:{index}")
            return number_formats[int(index - BUILTIN_FORMATS_MAX_SIZE)]

        for sheet in book.worksheets:
            visibility.append(
                (
                    sheet.title,
                    bool(sheet.sheet_format.zeroHeight),
                    tuple(
                        sorted(index for index, row in sheet.row_dimensions.items() if row.hidden)
                    ),
                )
            )
            if not full_precision:
                formats.append(
                    (
                        sheet.title,
                        tuple(
                            sorted(
                                (cell.coordinate, number_format(cast(Any, cell)._style))
                                for cell in sheet._cells.values()
                                if cell.value is not None
                            )
                        ),
                        tuple(
                            sorted(
                                (index, number_format(cast(Any, row)._style))
                                for index, row in sheet.row_dimensions.items()
                                if cast(Any, row)._style is not None
                            )
                        ),
                        tuple(
                            sorted(
                                (column.min, column.max, number_format(cast(Any, column)._style))
                                for column in sheet.column_dimensions.values()
                                if cast(Any, column)._style is not None
                            )
                        ),
                    )
                )
        return (
            tuple(visibility),
            (number_format(None), tuple(formats)) if not full_precision else (),
        )
    finally:
        book.close()


def _calculation_context(content: bytes) -> tuple:
    """Bind cached values to the original names, scope and numeric interpretation.

    Equal cell formulas are not equal inputs when a converter changes the
    definition of a referenced name or table, the date epoch or precision mode. Compare
    the OOXML declarations directly so built-in and sheet-local names that
    openpyxl consumes or omits cannot silently disappear from the check.
    """
    with ZipFile(io.BytesIO(content)) as archive:
        book = fromstring(archive.read("xl/workbook.xml"))
        tables = _table_context(archive)
    names = sorted(
        (node.get("name", ""), node.get("localSheetId", ""), node.text or "")
        for node in book.findall(f"{_NS}definedNames/{_NS}definedName")
    )
    properties = book.find(f"{_NS}workbookPr")
    calculation = book.find(f"{_NS}calcPr")
    full_precision = calculation is None or calculation.get("fullPrecision", "true") not in {
        "0",
        "false",
    }
    return (
        names,
        properties is not None and properties.get("date1904", "false") in {"1", "true"},
        full_precision,
        calculation.get("refMode", "A1") if calculation is not None else "A1",
        tables,
        _display_context(content, full_precision=full_precision),
    )


def _cached_values(content: bytes) -> dict:
    """Require a newly produced cached result for every formula, including empty text."""
    values = {}
    with ZipFile(io.BytesIO(content)) as archive:
        for sheet_name, path in _sheet_parts(archive):
            for cell in fromstring(archive.read(path)).iter(f"{_NS}c"):
                if cell.find(f"{_NS}f") is None:
                    continue
                cached = cell.find(f"{_NS}v")
                kind = cell.get("t", "n")
                if cached is None or (cached.text is None and kind != "str"):
                    raise _Unavailable("formula_recalculation_cache_missing")
                raw = cached.text or ""
                value: int | float | str | bool
                if kind == "n":
                    value = float(raw)
                    if not math.isfinite(value):
                        raise _Unavailable("formula_recalculation_nonfinite")
                    value = int(value) if value.is_integer() else value
                elif kind == "b" and raw in {"0", "1"}:
                    value = raw == "1"
                elif kind in {"str", "e"}:
                    value = raw
                else:
                    raise _Unavailable("formula_recalculation_cache_type_unsupported")
                values[sheet_name, cell.get("r")] = (kind, value)
    return values


def _expectations(plan: dict, formulas: dict) -> list[dict]:
    expected = plan.get("expected") or {}
    if not isinstance(expected, dict):
        raise _Unavailable("formula_recalculation_expectation_invalid")
    values = expected.get("formula_values", [])
    if (
        not isinstance(values, list)
        or len(values) > _MAX_FORMULAS
        or ("formula_values" in expected and not values)
    ):
        raise _Unavailable("formula_recalculation_expectation_invalid")
    seen = set()
    normalized = []
    for item in values:
        if (
            not isinstance(item, dict)
            or set(item) - {"sheet", "ref", "value", "abs_tolerance"}
            or not isinstance(item.get("sheet"), str)
            or not isinstance(item.get("ref"), str)
        ):
            raise _Unavailable("formula_recalculation_expectation_invalid")
        key = item["sheet"], item["ref"].upper()
        tolerance = item.get("abs_tolerance", 1e-9)
        if (
            key not in formulas
            or key in seen
            or "value" not in item
            or not isinstance(item["value"], (str, int, float, bool))
            or isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
            or (isinstance(item["value"], (int, float)) and not math.isfinite(item["value"]))
        ):
            raise _Unavailable("formula_recalculation_expectation_invalid")
        seen.add(key)
        normalized.append({**item, "ref": key[1]})
    return normalized


def _matches(actual: Any, expected: dict) -> bool:
    value = expected["value"]
    if type(value) in (int, float) and type(actual) in (int, float):
        return math.isclose(actual, value, rel_tol=0, abs_tol=expected.get("abs_tolerance", 1e-9))
    return type(actual) is type(value) and actual == value


def _samples(rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            **{key: value[:512] for key, value in row.items() if isinstance(value, str)},
            "truncated": any(isinstance(value, str) and len(value) > 512 for value in row.values()),
        }
        for row in rows[:_MAX_SAMPLES]
    ]


def recalculate_workbook(
    path: Path,
    plan: dict,
    *,
    artifact_sha256: str,
    timeout_seconds: float = 45,
) -> dict[str, Any]:
    """Return evidence bound to the original bytes; no business/tool action is repeated."""
    from app.application.employee_runtime.continuity_tool_wait import run_process

    result: dict[str, Any] = {
        "protocol": "xcagi.workbook-recalculation.v1",
        "status": "inconclusive",
        "code": "formula_recalculation_unavailable",
        "engine": "LibreOffice Calc",
        "artifact_sha256": artifact_sha256,
        "plan_sha256": canonical_digest(plan),
        "formula_recalculation_verified": False,
        "source_unchanged": False,
        "delivered_artifact_replaced": False,
    }
    try:
        content = path.read_bytes()
        if len(content) > _MAX_BYTES or hashlib.sha256(content).hexdigest() != artifact_sha256:
            raise _Unavailable("formula_recalculation_artifact_changed")
        _inspect_package(content, path.suffix.lower())
        sheets, formulas, literals = _cells(content)
        calculation_context = _calculation_context(content)
        expected = _expectations(plan, formulas)
        result.update(formula_count=len(formulas), expected_value_count=len(expected))
        if not formulas:
            result.update(status="not_required", code="formula_recalculation_no_formulas")
            return result
        engine = _engine_path()
        if engine is None:
            raise _Unavailable("formula_recalculation_engine_unavailable")
        if os.name != "posix":
            raise _Unavailable("formula_recalculation_process_isolation_unavailable")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
            raise _Unavailable("formula_recalculation_budget_invalid")
        deadline = time.monotonic() + timeout_seconds
        engine_env = {**os.environ, "SAL_USE_VCLPLUGIN": "svp", "SAL_DISABLE_OPENCL": "1"}
        with (
            _engine_slot(deadline),
            TemporaryDirectory(prefix="formula-qc-", dir=path.parent) as directory,
        ):
            root = Path(directory)
            profile = root / "profile"
            (profile / "user").mkdir(parents=True)
            (profile / "user/registrymodifications.xcu").write_text(_PROFILE, encoding="utf-8")
            profile_flag = f"-env:UserInstallation={profile.as_uri()}"
            version = run_process(
                [engine, profile_flag, "--version"],
                input=None,
                cwd=root,
                env=engine_env,
                limits=_PROCESS_LIMITS,
                timeout=min(5, deadline - time.monotonic()),
            )
            engine_version = version.stdout.strip()
            if version.returncode != 0 or not re.fullmatch(
                r"LibreOffice(?:Dev)? [^\r\n]{1,200}", engine_version
            ):
                raise _Unavailable("formula_recalculation_engine_identity_unavailable")
            result["engine_version"] = engine_version
            pinned = os.environ.get("LIBREOFFICE_EXPECTED_VERSION", "").strip()
            if not pinned:
                raise _Unavailable("formula_recalculation_engine_version_unpinned")
            if engine_version != pinned:
                raise _Unavailable("formula_recalculation_engine_version_mismatch")
            source, output = root / "source.xlsx", root / "calculated"
            source.write_bytes(content)
            output.mkdir()
            process = run_process(
                [
                    engine,
                    profile_flag,
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--nofirststartwizard",
                    "--convert-to",
                    "xlsx:Calc MS Excel 2007 XML",
                    "--outdir",
                    str(output),
                    str(source),
                ],
                input=None,
                cwd=root,
                env=engine_env,
                limits=_PROCESS_LIMITS,
                timeout=deadline - time.monotonic(),
            )
            calculated_path = output / "source.xlsx"
            result["engine_exit_code"] = process.returncode
            if process.returncode != 0 or not calculated_path.is_file():
                raise _Unavailable("formula_recalculation_engine_failed")
            if calculated_path.stat().st_size > _MAX_BYTES:
                raise _Unavailable("formula_recalculation_package_limit")
            calculated = calculated_path.read_bytes()
            result["output_sha256"] = hashlib.sha256(calculated).hexdigest()
            if result["output_sha256"] == artifact_sha256:
                raise _Unavailable("formula_recalculation_output_not_fresh")
            _inspect_package(calculated, ".xlsx")
            actual_sheets, actual_formulas, actual_literals = _cells(calculated)
            if (
                (sheets, literals) != (actual_sheets, actual_literals)
                or formulas.keys() != actual_formulas.keys()
                or any(
                    _formula_semantics(value) != _formula_semantics(actual_formulas[key])
                    for key, value in formulas.items()
                )
            ):
                raise _Unavailable("formula_recalculation_input_cells_changed")
            if _calculation_context(calculated) != calculation_context:
                raise _Unavailable("formula_recalculation_input_context_changed")
            values = _cached_values(calculated)
            if values.keys() != formulas.keys():
                raise _Unavailable("formula_recalculation_coverage_mismatch")
            rows = [
                {
                    "sheet": key[0],
                    "ref": key[1],
                    "formula": formulas[key],
                    "cached_type": values[key][0],
                    "value": values[key][1],
                }
                for key in sorted(formulas)
            ]
            errors = [row for row in rows if row["cached_type"] == "e"]
            mismatches = [
                item
                for item in expected
                if not _matches(values[item["sheet"], item["ref"]][1], item)
            ]
            verified = not errors and not mismatches
            result.update(
                status="verified" if verified else "failed",
                code=(
                    "formula_recalculation_verified"
                    if verified
                    else "formula_recalculation_error"
                    if errors
                    else "formula_recalculation_value_mismatch"
                ),
                formula_recalculation_verified=verified,
                expected_values_verified=bool(expected) and verified,
                formulas_sha256=canonical_digest(
                    [[key[0], key[1], formulas[key]] for key in sorted(formulas)]
                ),
                values_sha256=canonical_digest(rows),
                values=_samples(rows),
                values_truncated=len(rows) > _MAX_SAMPLES
                or any(row["truncated"] for row in _samples(rows)),
                formula_error_count=len(errors),
                formula_errors=_samples(errors),
                expectation_mismatch_count=len(mismatches),
                expectation_mismatches=_samples(mismatches),
            )
    except _Unavailable as exc:
        result.update(status="inconclusive", code=exc.code)
    except ProcessLimitsExceeded:
        result.update(status="inconclusive", code="formula_recalculation_resource_limit_exceeded")
    except ProcessLimitsUnavailable:
        result.update(
            status="inconclusive", code="formula_recalculation_resource_limits_unavailable"
        )
    except (TimeoutError, subprocess.TimeoutExpired):
        result.update(status="inconclusive", code="formula_recalculation_timeout")
    except (
        OSError,
        BadZipFile,
        InvalidFileException,
        ParseError,
        DefusedXmlException,
        ValueError,
        TokenizerError,
    ):
        result.update(status="inconclusive", code="formula_recalculation_unreadable")
    finally:
        try:
            result["source_unchanged"] = (
                hashlib.sha256(path.read_bytes()).hexdigest() == artifact_sha256
            )
        except OSError:
            result["source_unchanged"] = False
        if not result["source_unchanged"]:
            result.update(
                status="inconclusive",
                code="formula_recalculation_artifact_changed",
                formula_recalculation_verified=False,
                expected_values_verified=False,
            )
    return result
