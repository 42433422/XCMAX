"""Independently compare a scoped workbook artifact with its original typed plan."""

from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile

from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.workbook_write_contract import (
    WORKBOOK_NATIVE_PHASES,
    WORKBOOK_QC,
    WORKBOOK_READER,
    WORKBOOK_STRUCTURAL_PHASES,
    WORKBOOK_WRITER,
)


def scoped_workbook_employee(params: dict) -> str:
    employee_id = str(
        next(
            (params[k] for k in ("employee_id", "pack_id", "tool_name", "id") if params.get(k)), ""
        )
    ).strip()
    return employee_id if employee_id in (WORKBOOK_READER, WORKBOOK_WRITER) else ""


def is_workbook_write(params: dict) -> bool:
    return scoped_workbook_employee(params) == WORKBOOK_WRITER


def trusted_workbook_reader(params: dict) -> bool:
    """Only the signed bundled reader may run as an isolated read task."""
    if scoped_workbook_employee(params) != WORKBOOK_READER:
        return False
    from app.application.employee_runtime.loader import load_employee_pack_from_disk
    from app.application.employee_runtime.office_workers import is_trusted_workbook_pack

    try:
        return is_trusted_workbook_pack(
            WORKBOOK_READER, load_employee_pack_from_disk(WORKBOOK_READER)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


class WorkbookFormulaSyntaxError(ValueError):
    def __init__(self, field_path: str) -> None:
        super().__init__("工作簿公式语法无效")
        self.field_path = field_path


class WorkbookPlanError(ValueError):
    """The pinned writer rejected a plan before any file was saved."""


def _validate_formula_tokens(plan: dict) -> None:
    from openpyxl.formula import Tokenizer
    from openpyxl.formula.tokenizer import TokenizerError

    if not isinstance(plan, dict):
        return
    for phase_index, phase in enumerate(plan.get("phases") or []):
        if not isinstance(phase, dict) or phase.get("phase") != "formula_writes":
            continue
        writes = phase.get("writes")
        if not isinstance(writes, list):
            continue
        for write_index, write in enumerate(writes):
            formula = write.get("formula") if isinstance(write, dict) else None
            if not isinstance(formula, str) or not formula.startswith("="):
                continue  # The pinned writer owns the remaining plan-schema checks.
            field_path = f"input.plan.phases[{phase_index}].writes[{write_index}].formula"
            try:
                tokens = Tokenizer(formula).items
            except TokenizerError as exc:
                raise WorkbookFormulaSyntaxError(field_path) from exc
            array_depth = 0
            for token in tokens:
                if token.type == "ARRAY":
                    array_depth += 1 if token.subtype == "OPEN" else -1
                elif token.type == "SEP" and token.subtype == "ROW" and array_depth == 0:
                    # OOXML uses semicolons for array rows only; outside an
                    # array they cannot separate function arguments.
                    raise WorkbookFormulaSyntaxError(field_path)


@contextmanager
def _owned_template(source: str, context: dict):
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.infrastructure.tenant_scope import owned_tenant_id, tenant_scope

    actor = _bound_actor(context)
    tenant = str(context.get("tenant_id") or "")
    if (
        not tenant.isdecimal()
        or int(tenant) <= 0
        or str(actor.tenant_id) != tenant
        or owned_tenant_id() not in (None, int(tenant))
    ):
        raise PermissionError("模板核验缺少原账号租户范围")
    # Host contract capture/readback occurs outside the tool's tenant wrapper.
    # Restore only the already sealed, live actor scope for the original reader.
    with tenant_scope(int(tenant)), workflow_file_snapshot(source, context) as template:
        yield template


def capture_template(params: dict, context: dict) -> dict:
    source = (params.get("input") or {}).get("template_path")
    if not isinstance(source, str):
        return {}
    try:
        with _owned_template(source, context) as path:
            return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "suffix": path.suffix}
    except (OSError, ValueError, PermissionError):
        return {}


class _QcSourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # Default SourceFileLoader can read stale pyc or write new files into a
        # signed pack. Compile these trusted sources without either cache path.
        source = self.get_filename(fullname)
        return self.source_to_code(self.get_data(source), source)


class _QcSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, name: str, package_path: Path):
        self.name = name
        self.package_path = package_path.resolve()

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.name:
            module_path = self.package_path
        elif fullname.startswith(self.name + "."):
            parts = fullname[len(self.name) + 1 :].split(".")
            if not all(part.isidentifier() for part in parts):
                raise ModuleNotFoundError(fullname, name=fullname)
            module_path = self.package_path.joinpath(*parts)
        else:
            return None
        is_package = module_path.is_dir()
        source = module_path / "__init__.py" if is_package else module_path.with_suffix(".py")
        source = source.resolve()
        if not source.is_relative_to(self.package_path) or not source.is_file():
            # Do not let a later finder satisfy this namespace from a pyc file.
            raise ModuleNotFoundError(fullname, name=fullname)
        return importlib.util.spec_from_file_location(
            fullname,
            source,
            loader=_QcSourceLoader(fullname, str(source)),
            submodule_search_locations=[str(source.parent)] if is_package else None,
        )


@contextmanager
def _qc_package(pack: Path):
    """Load this trusted source package without sharing or writing bytecode caches."""
    package_path = Path(pack).resolve() / "backend" / "vendor" / "excel_qc"
    name = f"_xcagi_workbook_qc_{uuid4().hex}"
    finder = _QcSourceFinder(name, package_path)
    sys.meta_path.insert(0, finder)
    try:
        yield importlib.import_module(f"{name}.checks")
    finally:
        # No fixed package name or previous pack version can satisfy this load.
        for loaded in tuple(sys.modules):
            if loaded == name or loaded.startswith(name + "."):
                sys.modules.pop(loaded, None)
        sys.meta_path.remove(finder)


def review_workbook_write(params: dict, context: dict) -> tuple[dict, list[dict]]:
    from openpyxl.utils.exceptions import InvalidFileException

    from app.application.employee_runtime.executor import _import_module_from_path
    from app.application.employee_runtime.loader import load_employee_pack_from_disk
    from app.application.employee_runtime.office_workers import is_trusted_workbook_pack

    _validate_formula_tokens((params.get("input") or {}).get("plan") or {})
    pack = load_employee_pack_from_disk(WORKBOOK_WRITER)
    if not is_trusted_workbook_pack(WORKBOOK_WRITER, pack):
        raise PermissionError("没有可信的工作簿写入员")
    writer = _import_module_from_path(
        Path(pack["pack_dir"]) / "backend/vendor/excel_template_write/convert.py",
        "_xcagi_workbook_write_review",
    )
    if writer is None or not callable(getattr(writer, "review_literal_changes", None)):
        raise PermissionError("工作簿写入员没有数据变化预检能力")
    payload = params["input"]
    with _owned_template(payload["template_path"], context) as template:
        try:
            changes = writer.review_literal_changes(template, payload["plan"])
        except writer.PlanError as exc:
            raise WorkbookPlanError(str(exc)[:500]) from exc
        except (BadZipFile, InvalidFileException) as exc:
            raise ValueError("写入计划与原工作簿不兼容") from exc
        return {
            "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            "plan_sha256": canonical_digest(payload["plan"]),
            "changes_sha256": hashlib.sha256(
                json.dumps(changes, ensure_ascii=False, default=str, sort_keys=True).encode()
            ).hexdigest(),
            "requires_manual_approval": bool(changes),
        }, changes


def verify_workbook(run: Any, step: Any, call: Any, output: dict, context: dict) -> dict:
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.agent_orchestrator.verification_readback import _files, _report
    from app.application.employee_runtime.loader import (
        resolve_pack_dir,
        verify_direct_python_pack_trust,
    )
    from app.application.tools.workflow_spreadsheet_scope import _staging_root

    payload = step.params.get("input") or {}
    plan = payload.get("plan")
    original = (call.metadata.get("verification_contract") or {}).get("workbook_template") or {}
    artifacts = output.get("artifacts") or []
    if (
        not original.get("sha256")
        or not isinstance(plan, dict)
        or not isinstance(artifacts, list)
        or len(artifacts) != 1
        or not isinstance(artifacts[0], dict)
    ):
        return _report("inconclusive", "result_workbook_contract_missing", "workbook_qc")
    suffix = Path(str(artifacts[0].get("name") or "")).suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        return _report("failed", "result_workbook_format_invalid", "workbook_qc")
    if (name := payload.get("output_name")) and artifacts[0].get("name") != name:
        return _report("failed", "result_workbook_name_mismatch", "workbook_qc")
    files = _files(run, step, call, output, context, suffix)
    if files["status"] != "verified":
        return files
    pack = resolve_pack_dir(WORKBOOK_QC)
    if pack is None or not verify_direct_python_pack_trust(pack)[0]:
        return _report("inconclusive", "result_workbook_qc_unavailable", "workbook_qc")
    with _qc_package(Path(pack)) as module:
        if not callable(getattr(module, "run_qc", None)):
            return _report("inconclusive", "result_workbook_qc_unavailable", "workbook_qc")
        # Reopen the original owned input; a changed upload is not the preimage that
        # was approved and frozen before the producing worker ran.
        with _owned_template(payload["template_path"], context) as template:
            if hashlib.sha256(template.read_bytes()).hexdigest() != original["sha256"]:
                return _report("inconclusive", "result_workbook_template_changed", "workbook_qc")
            with TemporaryDirectory(prefix="workbook-qc-", dir=_staging_root()) as directory:
                filled = Path(directory) / ("result" + suffix)
                filled.write_bytes(read_verified_run_file(run.run_id, artifacts[0]))
                report = module.run_qc(filled, plan, template_path=template)
    sections = report.get("sections") or {}
    checked = {name: item.get("status") for name, item in sections.items()}
    native_count = sum(
        isinstance(phase, dict) and phase.get("phase") in WORKBOOK_NATIVE_PHASES
        for phase in plan.get("phases") or ()
    )
    style_count = sum(
        isinstance(phase, dict) and phase.get("phase") == "cell_styles"
        for phase in plan.get("phases") or ()
    )
    structural_count = sum(
        isinstance(phase, dict) and phase.get("phase") in WORKBOOK_STRUCTURAL_PHASES
        for phase in plan.get("phases") or ()
    )
    conformance_stats = (sections.get("conformance") or {}).get("stats") or {}
    valid = (
        report.get("verdict") == "PASS"
        and checked.get("conformance") == checked.get("formulas") == "pass"
        and (not plan.get("protected_ranges") or checked.get("protection") == "pass")
        and (not native_count or conformance_stats.get("native_phases_checked") == native_count)
        # 旧版 QC 不检查样式/结构操作时不能静默放行已声明的计划。
        and (not style_count or int(conformance_stats.get("style_cells_checked") or 0) > 0)
        and (
            not structural_count
            or conformance_stats.get("structural_phases_checked") == structural_count
        )
    )
    status = (
        "verified" if valid else "failed" if report.get("verdict") == "FAIL" else "inconclusive"
    )
    quality = _report(
        status,
        "result_verified" if valid else "result_workbook_qc_unmet",
        "workbook_qc",
        verification_scope=(
            "planned_cells_formulas_protected_ranges_structural_and_native_objects"
            if native_count
            else "planned_cells_formulas_protected_ranges_and_structural_operations"
            if structural_count
            else "planned_cells_formulas_and_protected_ranges"
        ),
        template_sha256=original["sha256"],
        artifact_sha256=artifacts[0]["metadata"]["sha256"],
        sections=checked,
        cell_changes=report.get("cell_changes"),
        formula_recalculation_verified=False,
    )
    quality["checks"] = files["checks"] + quality["checks"]
    return quality
