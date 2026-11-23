"""Private frozen fixtures around the original workflow/native-file runtime.

This is an assertion adapter, not an executor: the product converter, SQL models,
WorkflowEngine and EmployeeRuntimeClient do the work. Independent csv/openpyxl
checks run in the parent; reference bytes never enter the employee process.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from modstore_server.retort_experiment_surfaces import WORKFLOW_BUSINESS_MEASUREMENT

REPLAY_SCHEMA = "xcagi.workflow-customer-replay/v1"
ASSETS_SCHEMA = "xcagi.workflow-business-assets/v1"
MAX_REPLAY_BYTES = 180_000
MAX_OUTPUT_BYTES = 8_000_000


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _relative(value):
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or "\\" in value
        or Path(value).as_posix() != value
        or value == "."
        or "{{" in value
    ):
        raise ValueError("training_replay_path_invalid")
    return value


def _bytes(item):
    try:
        raw = base64.b64decode(item["base64"], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("training_replay_bytes_invalid") from exc
    if not raw or len(raw) > MAX_REPLAY_BYTES or _sha(raw) != item.get("sha256"):
        raise ValueError("training_replay_bytes_changed")
    return raw


def _blob(path, raw):
    if not raw or len(raw) > MAX_REPLAY_BYTES:
        raise ValueError("training_replay_payload_too_large")
    return {
        "path": _relative(path),
        "sha256": _sha(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _read_asset(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_REPLAY_BYTES + 1)
    if len(raw) > MAX_REPLAY_BYTES:
        raise ValueError("training_replay_payload_too_large")
    return raw


def _bounded(value):
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_REPLAY_BYTES:
        raise ValueError("training_replay_payload_too_large")


def _workspace_relative(value, workspace):
    path = Path(str(value))
    if path.is_absolute():
        path = path.relative_to(workspace)
    return _relative(path.as_posix())


def _native_steps(assets, contract):
    """Only frozen source files and outputs of the approved prefix are executable."""
    from modstore_server.workflow_customer_delivery import (
        _has_node_reference,
        delivery_nodes,
    )
    from modstore_server.workflow_variables import resolve_value

    packages = {item["employee_id"]: item for item in assets["packages"]}
    readable = {item["path"] for item in assets["input_files"]}
    steps = []
    nodes = delivery_nodes(contract)
    for node in nodes:
        original = node.get("node_input") or node.get("deferred_input_mapping") or {}
        payload = resolve_value(
            original, {"global": assets["input_data"], "result": assets["input_data"], "nodes": {}}
        )
        actions = packages[node["employee_id"]]["effective_config"].get("actions") or {}
        actions = actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
        direct = actions.get("direct_python") or {}
        if _has_node_reference(original.get("output_relpath")) or _has_node_reference(
            original.get("template_relpath")
        ):
            raise ValueError("training_replay_dynamic_destination_unavailable")
        output = payload.get("output_relpath") or direct.get("default_output_relpath")
        if not output:
            raise ValueError("training_replay_native_output_required")
        output = _workspace_relative(output, assets["workspace"])
        if output in readable:
            raise ValueError("training_replay_output_overwrites_frozen_input")
        declared = node.get("customer_deliverables", [output] if len(nodes) == 1 else [])
        if any(path != output for path in declared):
            raise ValueError("training_replay_native_deliverables_changed")
        steps.append(
            {
                "employee_id": node["employee_id"],
                "input_paths": sorted(readable),
                "output_path": output,
                "customer_deliverables": declared,
            }
        )
        readable.add(output)
    return steps


def _source_hashes(replay):
    """Read business file roles from the original contract, never template metadata."""
    from modstore_server.workflow_customer_delivery import (
        _has_node_reference,
        delivery_nodes,
    )
    from modstore_server.workflow_variables import resolve_value

    if (
        not isinstance(replay, dict)
        or not isinstance(replay.get("assets"), dict)
        or not isinstance(replay.get("contract"), dict)
    ):
        raise TypeError("training_replay_original_sources_required")
    assets = replay["assets"]
    files = {item["path"]: item for item in assets.get("input_files") or []}
    hashes = set()
    for node in delivery_nodes(replay["contract"]):
        mapping = node.get("node_input") or node.get("deferred_input_mapping") or {}
        value = mapping.get("file_path")
        if not value or _has_node_reference(value):
            continue
        value = resolve_value(
            value, {"global": assets["input_data"], "result": assets["input_data"], "nodes": {}}
        )
        path = _workspace_relative(value, assets["workspace"])
        if path not in files:
            raise ValueError("training_replay_original_source_unavailable")
        hashes.add(_sha(_bytes(files[path])))
    if not hashes:
        raise ValueError("training_replay_original_sources_required")
    return sorted(hashes)


def source_group_sha256(replay):
    """Renames and template changes cannot move the same business source across splits."""
    return _digest(_source_hashes(replay))


def validate_replay_manifest(replay):
    """Recompute portable bytes/contract bindings; SQL ownership is checked by the gate."""
    if not isinstance(replay, dict):
        raise TypeError("training_business_replay_unavailable")
    _bounded(replay)
    if replay.get("schema") != REPLAY_SCHEMA or replay.get("replay_ready") is not True:
        raise ValueError("training_business_replay_unavailable")
    assets, contract = replay.get("assets"), replay.get("contract")
    if not isinstance(assets, dict) or not isinstance(contract, dict):
        raise TypeError("training_replay_contract_required")
    if (
        not isinstance(assets.get("workspace"), str)
        or not Path(assets["workspace"]).is_absolute()
        or assets["workspace"] == "/"
        or not isinstance(replay.get("user_id"), int)
        or isinstance(replay["user_id"], bool)
        or replay["user_id"] <= 0
    ):
        raise ValueError("training_replay_workspace_invalid")
    group = source_group_sha256(replay)
    frozen = {
        "schema": ASSETS_SCHEMA,
        "replay_ready": True,
        "source_group_sha256": group,
        "assets": assets,
    }
    if (
        replay.get("source_group_sha256") != group
        or _digest({**contract, "business_replay": frozen}) != replay.get("contract_sha256")
        or _digest(assets.get("input_data")) != replay.get("input_sha256")
        or contract.get("execution_input_sha256") != replay.get("input_sha256")
        or any(
            contract.get(key) != replay.get(key)
            for key in ("execution_id", "workflow_id", "user_id", "graph_fingerprint")
        )
        or not isinstance(replay.get("source_evidence_sha256"), str)
        or len(replay["source_evidence_sha256"]) != 64
    ):
        raise ValueError("training_replay_contract_changed")
    from modstore_server.workflow_customer_delivery import delivery_nodes

    nodes = delivery_nodes(contract)
    if assets.get("employee_ids") != [node["employee_id"] for node in nodes]:
        raise ValueError("training_replay_employees_changed")
    inputs, expected = assets.get("input_files"), assets.get("expected_files")
    packages = assets.get("packages")
    if not all(isinstance(items, list) and items for items in (inputs, expected, packages)):
        raise ValueError("training_replay_assets_required")
    paths = []
    for item in [*inputs, *expected]:
        paths.append(_relative(item["path"]))
        _bytes(item)
    if len(paths) != len(set(paths)):
        raise ValueError("training_replay_reference_overlaps_source")
    ids = [item.get("employee_id") for item in packages]
    if len(ids) != len(set(ids)) or set(ids) != set(assets["employee_ids"]):
        raise ValueError("training_replay_packages_changed")
    for package in packages:
        path = _relative(package["path"])
        if Path(path).name != path or Path(path).suffix not in {
            ".xcemp",
            ".zip",
            ".xcmod",
        }:
            raise ValueError("training_replay_package_path_invalid")
        from modman.archive_import import MAX_FILES, MAX_UNPACKED_BYTES
        from modstore_server.employee_runtime import (
            normalize_manifest_legacy_deepseek_to_auto,
        )

        try:
            with zipfile.ZipFile(io.BytesIO(_bytes(package))) as archive:
                names = archive.namelist()
                if (
                    len(names) != len(set(names))
                    or len(names) > MAX_FILES
                    or sum(item.file_size for item in archive.infolist()) > MAX_UNPACKED_BYTES
                ):
                    raise ValueError("training_replay_archive_invalid")
                manifest = json.loads(archive.read(f"{package['employee_id']}/manifest.json"))
                normalize_manifest_legacy_deepseek_to_auto(manifest)
                if manifest != package["manifest"]:
                    raise ValueError("training_replay_package_manifest_changed")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("training_replay_archive_invalid") from exc
        bindings = [
            node["execution_binding"]
            for node in nodes
            if node["employee_id"] == package["employee_id"]
        ]
        if any(
            binding.get("archive_sha256") != package["sha256"]
            or binding.get("config_sha256") != _digest(package["effective_config"])
            or binding.get("manifest_sha256") != _digest(package["manifest"])
            or binding.get("version") != package["version"]
            for binding in bindings
        ):
            raise ValueError("training_replay_package_binding_changed")
    for item in expected:
        if Path(item["path"]).suffix.lower() not in {".xlsx", ".csv"}:
            raise ValueError("training_replay_reference_format_unsupported")
    steps = _native_steps(assets, contract)
    if {item["path"] for item in expected} != {
        path for step in steps for path in step["customer_deliverables"]
    }:
        raise ValueError("training_replay_required_outputs_changed")
    return {
        "manifest_sha256": _digest(replay),
        "source_group_sha256": group,
        "source_sha256": _source_hashes(replay),
        "expected_reference_sha256": {item["path"]: item["sha256"] for item in expected},
        "expected_output_paths": [item["path"] for item in expected],
    }


def capture_business_replay(db, contract, inputs):
    """Optional operator-configured oracle capture, before any original native execution."""
    from modstore_server.catalog_archive_integrity import archive_path
    from modstore_server.catalog_store import files_dir
    from modstore_server.employee_runtime import (
        load_employee_pack_resolved,
        parse_employee_config_v2,
    )
    from modstore_server.employee_runtime_policy import (
        apply_policy_to_config,
        policy_for_employee,
    )
    from modstore_server.strategic_execution_contract import _workspace_file
    from modstore_server.workflow_customer_delivery import (
        _has_node_reference,
        delivery_nodes,
    )
    from modstore_server.workflow_nl_training import _policies
    from modstore_server.workflow_variables import resolve_value

    policies = [
        p
        for p in _policies()
        if contract["user_id"] in p["growthbook"]["lifecycle"].get("cohort_user_ids", [])
    ]
    if len(policies) != 1 or not policies[0].get("offline_business_replay"):
        return None
    try:
        nodes, owner = delivery_nodes(contract), contract["user_id"]
        roots = {node["input_data"]["workspace_root"] for node in nodes}
        if len(roots) != 1:
            raise ValueError("training_replay_workspace_changed")
        workspace = roots.pop()
        files, packages = {}, {}
        for node in nodes:
            raw = node.get("node_input") or node.get("deferred_input_mapping") or {}
            payload = resolve_value(raw, {"global": inputs, "result": inputs, "nodes": {}})
            for key in ("file_path", "template_relpath"):
                if _has_node_reference(raw.get(key)):
                    if key == "template_relpath":
                        raise ValueError("training_replay_dynamic_template_unavailable")
                    continue
                if payload.get(key):
                    path = _workspace_file(str(payload[key]), workspace, owner, exists=True)
                    relative = path.relative_to(Path(workspace)).as_posix()
                    files[relative] = _blob(relative, _read_asset(path))
            employee = node["employee_id"]
            pack = load_employee_pack_resolved(db, employee, user_id=owner, execute=True)
            archive = archive_path(pack["stored_filename"], pack["sha256"], (files_dir(),))
            if archive is None:
                raise ValueError("training_replay_package_unavailable")
            config, _ = apply_policy_to_config(
                employee, deepcopy(parse_employee_config_v2(pack["manifest"]))
            )
            packages[employee] = {
                **_blob(pack["stored_filename"], _read_asset(archive)),
                "employee_id": employee,
                "version": pack["version"],
                "manifest": pack["manifest"],
                "effective_config": config,
                "runtime_policy": policy_for_employee(employee),
            }
            actions = config.get("actions") or {}
            actions = (
                actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
            )
            template = (actions.get("direct_python") or {}).get("default_template_relpath")
            if template and not payload.get("template_relpath"):
                path = Path(template)
                candidate = path if path.is_absolute() else Path(workspace) / path
                if candidate.exists():
                    path = _workspace_file(str(candidate), workspace, owner, exists=True)
                    relative = path.relative_to(Path(workspace)).as_posix()
                    files[relative] = _blob(relative, _read_asset(path))
        assets = {
            "input_data": deepcopy(inputs),
            "workspace": workspace,
            "employee_ids": [node["employee_id"] for node in nodes],
            "input_files": sorted(files.values(), key=lambda item: item["path"]),
            "packages": sorted(packages.values(), key=lambda item: item["employee_id"]),
        }
        steps = _native_steps(assets, contract)
        group = source_group_sha256({"assets": assets, "contract": contract})
        settings = policies[0]["offline_business_replay"]
        if not isinstance(settings, dict) or not isinstance(settings.get("references"), dict):
            raise TypeError("training_replay_independent_reference_required")
        references = settings["references"].get(group)
        if not isinstance(references, list) or not references:
            raise ValueError("training_replay_independent_reference_required")
        expected, required = [], [path for step in steps for path in step["customer_deliverables"]]
        for reference in references:
            output = _relative(reference["output_path"])
            path = _workspace_file(reference["reference_path"], workspace, owner, exists=True)
            relative = path.relative_to(Path(workspace)).as_posix()
            if (
                relative == output
                or relative in files
                or relative in {step["output_path"] for step in steps}
            ):
                raise ValueError("training_replay_reference_not_independent")
            blob = _blob(output, _read_asset(path))
            if blob["sha256"] != reference.get("sha256"):
                raise ValueError("training_replay_reference_changed")
            expected.append(blob)
        if set(required) != {item["path"] for item in expected} or not required:
            raise ValueError("training_replay_required_outputs_changed")
        assets["expected_files"] = sorted(expected, key=lambda item: item["path"])
        captured = {
            "schema": ASSETS_SCHEMA,
            "replay_ready": True,
            "source_group_sha256": group,
            "assets": assets,
        }
        _bounded(captured)
        return captured
    except (OSError, ValueError, KeyError, TypeError):
        # Production delivery does not require training fixtures. Never re-read an
        # unfrozen source after execution and represent it as original evidence.
        return {
            "schema": ASSETS_SCHEMA,
            "replay_ready": False,
            "reason": "training_replay_capture_unavailable",
        }


def export_customer_replay(binding, execution_input, source_evidence_sha256):
    contract = deepcopy(binding.get("customer_delivery") or {})
    frozen = contract.pop("business_replay", {})
    contract_sha = contract.pop("contract_sha256", None)
    replay = {
        "schema": REPLAY_SCHEMA,
        "replay_ready": False,
        **{
            key: binding.get(key)
            for key in ("execution_id", "workflow_id", "user_id", "graph_fingerprint")
        },
        "input_sha256": _digest(execution_input),
        "contract_sha256": contract_sha,
        "source_evidence_sha256": source_evidence_sha256,
    }
    if not frozen.get("replay_ready"):
        return {**replay, "reason": "training_replay_original_snapshot_required"}
    replay.update(
        replay_ready=True,
        contract=contract,
        assets=frozen["assets"],
        source_group_sha256=frozen["source_group_sha256"],
    )
    validate_replay_manifest(replay)
    return replay


def _workbook(raw):
    from openpyxl import load_workbook

    # Reject oversized zip expansion before openpyxl allocates cell objects.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_OUTPUT_BYTES:
            raise ValueError("training_replay_workbook_too_large")
    workbook = load_workbook(io.BytesIO(raw), data_only=False, keep_links=False)
    values = load_workbook(io.BytesIO(raw), data_only=True, keep_links=False)
    try:
        if any(sheet.max_row * sheet.max_column > 250_000 for sheet in workbook):
            raise ValueError("training_replay_workbook_too_large")
        result = []
        for sheet in workbook:
            rows = []
            for row in sheet.iter_rows():
                cells = []
                for cell in row:
                    cached = values[sheet.title][cell.coordinate].value
                    if cell.data_type == "f" and cached is None:
                        raise ValueError("training_replay_formula_value_unverified")
                    cells.append((cell.data_type, cell.value, cached, cell.number_format))
                rows.append(cells)
            result.append(
                (
                    sheet.title,
                    sorted(str(item) for item in sheet.merged_cells.ranges),
                    rows,
                )
            )
        return result
    finally:
        workbook.close()
        values.close()


def _equal_files(path, actual, expected):
    if Path(path).suffix.lower() == ".xlsx":
        return _workbook(actual) == _workbook(expected)
    if actual == expected:
        return True
    try:
        reference = expected.decode("utf-8-sig")
        dialects = []
        for delimiter in ",;\t|":
            try:
                dialect = csv.Sniffer().sniff(reference, delimiters=delimiter)
                # Match the native DictWriter's defaults: whitespace is cell data,
                # and doubled quote characters are escapes, even if absent in gold.
                dialect.skipinitialspace = False
                dialect.doublequote = True
                rows = list(csv.reader(io.StringIO(reference, newline=""), dialect, strict=True))
            except csv.Error:
                continue
            if rows and len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows):
                dialects.append((dialect, rows))
        # Only the frozen oracle chooses the dialect. Ambiguous/single-column
        # references can establish exact bytes, never inferred semantic success.
        if len(dialects) != 1:
            return False
        dialect, rows = dialects[0]
        return (
            list(
                csv.reader(
                    io.StringIO(actual.decode("utf-8-sig"), newline=""), dialect, strict=True
                )
            )
            == rows
        )
    except (csv.Error, UnicodeError):
        return False


def _remap(value, original, workspace):
    if isinstance(value, dict):
        return {key: _remap(item, original, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap(item, original, workspace) for item in value]
    if isinstance(value, str) and (value == original or value.startswith(original + "/")):
        return workspace + value[len(original) :]
    return value


def _run_worker(request, directory, env, *, timeout=60):
    from modstore_server.self_maintenance_subprocess import terminate_subprocess

    with subprocess.Popen(
        [sys.executable, "-m", __name__, "--worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=directory,
        env=env,
        start_new_session=os.name == "posix",
    ) as proc:
        try:
            stdout, stderr = proc.communicate(json.dumps(request), timeout=timeout)
            return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        finally:
            # Reap the owned group before Popen closes its pipes, including on timeout.
            terminate_subprocess(proc, process_group=True)


def evaluate_business_replay(output, source):
    """Never trust a provider's sandbox_ok, score, customer verdict or file declaration."""
    failed = {
        "pass": False,
        "score": 0,
        "measurement_scope": WORKFLOW_BUSINESS_MEASUREMENT,
        "runtime_verified": False,
        "reason": "training_business_replay_blocked",
    }
    try:
        replay = source["customer_business_replay"]
        identity = validate_replay_manifest(replay)
        assets = replay["assets"]
        with tempfile.TemporaryDirectory(prefix="workflow-business-replay-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            for item in assets["input_files"]:
                path = workspace / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_bytes(item))
            # The worker receives no independent reference bytes, hashes or paths.
            worker_assets = {
                key: deepcopy(value) for key, value in assets.items() if key != "expected_files"
            }
            worker_source = {
                key: deepcopy(value)
                for key, value in source.items()
                if key not in {"customer_business_replay", "execution_feedback"}
            }
            request = {
                "output": output,
                "source": worker_source,
                "assets": worker_assets,
                "workspace": str(workspace),
                "user_id": replay["user_id"],
                "steps": _native_steps(assets, replay["contract"]),
            }
            project = Path(__file__).resolve().parents[1]
            repository = project.parents[1]
            env = {
                key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "LANG") if key in os.environ
            }
            env.update(
                PYTHONPATH=os.pathsep.join((str(project), str(repository / "FHD"))),
                HOME=str(root),
                TMPDIR=str(root),
                DATABASE_URL=f"sqlite:///{root / 'replay.db'}",
                MODSTORE_CATALOG_DIR=str(root / "catalog"),
                MODSTORE_RUNTIME_DIR=str(root / "runtime"),
                MODSTORE_DATA_DIR=str(root / "data"),
                MODSTORE_TENANT_WORKSPACE_ROOT=str(workspace),
                MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK="0",
                MODSTORE_REPO_ROOT=str(workspace),
            )
            result = _run_worker(request, root, env)
            if result.returncode or not (root / "executed.json").exists():
                return failed
            executed = json.loads((root / "executed.json").read_text())
            if executed.get("runtime_verified") is not True:
                return failed
            hashes, matches = {}, executed.get("ok") is True
            for item in assets["expected_files"]:
                path = workspace / item["path"]
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or not path.resolve().is_relative_to(workspace)
                    or path.stat().st_size > MAX_OUTPUT_BYTES
                ):
                    matches = False
                    continue
                actual = path.read_bytes()
                hashes[item["path"]] = _sha(actual)
                matches = _equal_files(item["path"], actual, _bytes(item)) and matches
            evidence = {
                **{
                    key: identity[key]
                    for key in (
                        "manifest_sha256",
                        "source_group_sha256",
                        "expected_reference_sha256",
                    )
                },
                "contract_sha256": replay["contract_sha256"],
                "source_evidence_sha256": replay["source_evidence_sha256"],
                "output_sha256": hashes,
            }
            return {
                "pass": matches,
                "score": int(matches),
                "reason": (
                    WORKFLOW_BUSINESS_MEASUREMENT
                    if matches
                    else "training_business_artifact_mismatch"
                ),
                "measurement_scope": WORKFLOW_BUSINESS_MEASUREMENT,
                "runtime_verified": True,
                "business_evidence": evidence,
            }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
        zipfile.BadZipFile,
    ):
        return failed


def _worker(request):
    """Restore the frozen native packages and call the existing product runtime."""
    from cryptography.fernet import Fernet
    from sqlalchemy import select

    from modstore_server.catalog_store import files_dir
    from modstore_server.employee_runtime import (
        load_employee_pack_resolved,
        parse_employee_config_v2,
    )
    from modstore_server.employee_runtime_policy import (
        apply_policy_to_config,
        save_policy,
    )
    from modstore_server.models import (
        Base,
        CatalogItem,
        User,
        Workflow,
        WorkflowEdge,
        WorkflowNode,
        get_engine,
        get_session_factory,
    )
    from modstore_server.services.employee import (
        InProcessEmployeeRuntimeClient,
        set_default_employee_client,
    )
    from modstore_server.strategic_execution_contract import (
        _workspace_file,
        freeze_execution,
        validate_input,
    )
    from modstore_server.workflow_api.helpers import _restore_workflow_from_snapshot
    from modstore_server.workflow_customer_delivery import _serial_employees
    from modstore_server.workflow_engine import WorkflowEngine
    from modstore_server.workflow_nl_apply import _apply_generated_response

    assets, source, workspace = (
        request["assets"],
        request["source"],
        request["workspace"],
    )
    # Credentials and policy secrets are disposable and never copied from production.
    os.environ["MODSTORE_LLM_MASTER_KEY"] = Fernet.generate_key().decode("ascii")
    Base.metadata.create_all(get_engine())
    save_policy(
        {"employees": {item["employee_id"]: item["runtime_policy"] for item in assets["packages"]}}
    )

    class FrozenFileClient(InProcessEmployeeRuntimeClient):
        executed = 0

        def execute_task(
            self,
            *,
            employee_id,
            task,
            input_data=None,
            user_id=None,
            bench_llm_override=None,
        ):
            # The original engine has already resolved global/node variables here.
            if (
                user_id != request["user_id"]
                or employee_id not in assets["employee_ids"]
                or bench_llm_override
            ):
                raise ValueError("training_replay_runtime_identity_changed")
            frozen = freeze_execution(
                user_id, {"employee_id": employee_id, "input_data": input_data}
            )
            payload = frozen["input_data"]
            if payload["workspace_root"] != workspace or not payload.get("file_path"):
                raise ValueError("training_replay_native_source_required")
            step = request["steps"][self.executed]
            if step["employee_id"] != employee_id:
                raise ValueError("training_replay_runtime_step_changed")
            for key in ("file_path", "template_relpath"):
                if payload.get(key):
                    path = _workspace_file(str(payload[key]), workspace, user_id, exists=True)
                    if path.relative_to(workspace).as_posix() not in step["input_paths"]:
                        raise ValueError("training_replay_unfrozen_source")
            package = next(
                item for item in assets["packages"] if item["employee_id"] == employee_id
            )
            actions = package["effective_config"].get("actions") or {}
            actions = (
                actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
            )
            output = payload.get("output_relpath") or (actions.get("direct_python") or {}).get(
                "default_output_relpath"
            )
            if _workspace_relative(output, workspace) != step["output_path"]:
                raise ValueError("training_replay_unapproved_output")
            payload.update(
                suppress_handoff=True,
                suppress_employee_im=True,
                suppress_lifecycle_events=True,
            )
            result = super().execute_task(
                employee_id=employee_id, task=task, input_data=payload, user_id=user_id
            )
            self.executed += 1
            return result

    client = FrozenFileClient()
    set_default_employee_client(client)
    with get_session_factory()() as db:
        user = User(
            id=request["user_id"],
            username="workflow-offline-replay",
            password_hash="unusable",
            is_enterprise=True,
        )
        db.add(user)
        db.flush()
        for item in assets["packages"]:
            (files_dir() / item["path"]).write_bytes(_bytes(item))
            db.add(
                CatalogItem(
                    pkg_id=item["employee_id"],
                    version=item["version"],
                    name=item["employee_id"],
                    author_id=user.id,
                    artifact="employee_pack",
                    is_public=False,
                    stored_filename=item["path"],
                    sha256=item["sha256"],
                )
            )
        workflow = Workflow(user_id=user.id, name=source["graph"]["name"])
        db.add(workflow)
        db.flush()
        _restore_workflow_from_snapshot(db, workflow, source["graph"])
        db.commit()
        for item in assets["packages"]:
            pack = load_employee_pack_resolved(
                db, item["employee_id"], user_id=user.id, execute=True
            )
            config, _ = apply_policy_to_config(
                item["employee_id"],
                deepcopy(parse_employee_config_v2(pack["manifest"])),
            )
            actions = config.get("actions") or {}
            actions = (
                actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
            )
            if _digest(config) != _digest(item["effective_config"]) or actions.get("handlers") != [
                "direct_python"
            ]:
                raise ValueError("training_replay_runtime_config_changed")
        applied = _apply_generated_response(
            db,
            user,
            workflow=workflow,
            result={"ok": True, "content": request["output"]},
            brief=source["brief"],
            target_employee_pack_id=source.get("target_employee_pack_id"),
            target_employee_label=source.get("target_employee_label"),
            preset_nodes=source.get("preset_nodes"),
            validate_in_session=True,
        )
        if applied.get("ok") is not True or applied.get("sandbox_ok") is not True:
            return
        ordered = _serial_employees(
            list(db.scalars(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id))),
            list(db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id))),
        )
        configs = [json.loads(node.config) for node in ordered]
        if [config.get("employee_id") for config in configs] != assets["employee_ids"]:
            raise ValueError("training_replay_employee_chain_changed")
        original = assets["workspace"]
        for node, config, step in zip(ordered, configs, request["steps"], strict=True):
            if (
                "customer_deliverables" in config
                and config["customer_deliverables"] != step["customer_deliverables"]
            ):
                raise ValueError("training_replay_required_outputs_changed")
            mapping = config.get("input_mapping")
            if not isinstance(mapping, dict) or not mapping or config.get("retry_count", 0) != 0:
                raise ValueError("training_replay_native_mapping_required")
            validate_input(mapping)
            config = _remap(config, original, workspace)
            mapping = config["input_mapping"]
            for field in ("file_path", "output_relpath", "template_relpath"):
                value = mapping.get(field)
                if value and "{{" not in str(value):
                    path = Path(str(value))
                    if path.is_absolute():
                        path = path.relative_to(workspace)
                    _relative(path.as_posix())
                    if field == "file_path" and path.as_posix() not in step["input_paths"]:
                        raise ValueError("training_replay_unfrozen_source")
            mapping.update(workspace_root=workspace, project_root=workspace)
            mapping.setdefault("output_relpath", step["output_path"])
            config["timeout_seconds"] = min(int(config.get("timeout_seconds") or 30), 30)
            node.config = json.dumps(config)
        db.commit()
        inputs = _remap(assets["input_data"], original, workspace)
        inputs.update(workspace_root=workspace, project_root=workspace)
        report = WorkflowEngine().run_sandbox(
            db, workflow, inputs, user_id=user.id, mock_employees=False
        )
        Path("executed.json").write_text(
            json.dumps(
                {
                    "runtime_verified": client.executed == len(assets["employee_ids"]),
                    "ok": report.get("ok") is True,
                }
            )
        )


if __name__ == "__main__":
    _worker(json.load(sys.stdin))
