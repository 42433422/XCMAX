"""Owned, approved workflow files produced by the existing native employee runtime."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from modstore_server.customer_service_tools import json_loads
from modstore_server.eventing.db_outbox import enqueue
from modstore_server.models import (
    CustomerValueReceipt,
    OutboxEvent,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.strategic_portfolio import digest
from modstore_server.workflow_sandbox_state import workflow_graph_fingerprint

START_EVENT = "workflow.execution.feedback_started"
CLAIM_EVENT = "workflow.customer.delivery_started"
PRODUCED_EVENT = "workflow.customer.delivery_produced"
COMPLETION_PROTOCOL = "workflow.customer.graph-return.v1"
ARTIFACT_SOURCE = "native_direct_python_workflow_output"
MAX_ARTIFACT_BYTES = 64_000_000


def delivery_nodes(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Read legacy single-node contracts and the frozen ordered native graph."""
    nodes = contract.get("nodes")
    if nodes is None:
        return [contract]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("customer delivery has no required native nodes")
    return nodes


def delivery_node(contract: dict[str, Any], node_id: int) -> dict[str, Any]:
    matches = [node for node in delivery_nodes(contract) if node.get("node_id") == node_id]
    if len(matches) != 1:
        raise ValueError("customer delivery node is not uniquely bound to the approved graph")
    return matches[0]


def _serial_employees(nodes: list[Any], edges: list[Any]) -> list[Any]:
    """Match the existing engine's unconditional path, with no skipped/extra nodes."""
    starts = [node for node in nodes if node.node_type == "start"]
    ends = [node for node in nodes if node.node_type == "end"]
    by_id = {node.id: node for node in nodes}
    outgoing = {edge.source_node_id: edge.target_node_id for edge in edges}
    if (
        len(starts) != 1
        or len(ends) != 1
        or len(nodes) < 3
        or any(node.node_type not in {"start", "employee", "end"} for node in nodes)
        or len(edges) != len(nodes) - 1
        or len(outgoing) != len(edges)
        or any(str(edge.condition or "").strip() for edge in edges)
    ):
        raise ValueError("customer delivery requires one unconditional native employee chain")
    ordered, seen = [], set()
    node = starts[0]
    while node is not None and node.id not in seen:
        ordered.append(node)
        seen.add(node.id)
        node = by_id.get(outgoing.get(node.id))
    if (
        node is not None
        or len(ordered) != len(nodes)
        or ordered[-1].id != ends[0].id
        or any(item.node_type != "employee" for item in ordered[1:-1])
        or ends[0].id in outgoing
    ):
        raise ValueError("customer delivery cannot skip, branch or repeat required native nodes")
    return ordered[1:-1]


def _event(db: Any, event_id: str) -> Any:
    return db.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))


def _customer(db: Any, user_id: int) -> Any:
    user = db.get(User, user_id, populate_existing=True)
    if (
        user is None
        or user.is_admin
        or not user.is_enterprise
        or user.deleted_at is not None
        or user.account_state in {"disabled", "suspended", "blocked", "deleted"}
        or getattr(user, "is_active", True) is False
    ):
        raise ValueError("workflow delivery requires the original active enterprise customer")
    return user


def prepare_customer_delivery(
    db: Any, execution: Any, binding: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Freeze the paid goal and every native node of the actually approved graph."""
    from modstore_server.customer_value_lifecycle_api import _authoritative_order
    from modstore_server.strategic_customer_outcomes import load_customer_goal_bindings

    owner = int(execution.user_id)
    _customer(db, owner)
    workflow = db.get(Workflow, execution.workflow_id, populate_existing=True)
    inputs = json_loads(execution.input_data, {})
    request = inputs.get("customer_delivery") if isinstance(inputs, dict) else None
    if (
        workflow is None
        or workflow.user_id != owner
        or not isinstance(request, dict)
        or set(request) != {"order_no", "customer_goal_id"}
        or any(not isinstance(value, str) or not value.strip() for value in request.values())
        or binding.get("user_id") != owner
        or binding.get("workflow_id") != workflow.id
        or binding.get("input_sha256") != digest(inputs)
        or binding.get("graph_fingerprint") != workflow_graph_fingerprint(db, workflow.id)
    ):
        raise ValueError("workflow customer delivery identity is incomplete or changed")
    _authoritative_order(request["order_no"], owner)
    goal = load_customer_goal_bindings(owner, request["order_no"], [request["customer_goal_id"]])[0]
    agreement = db.scalar(
        select(CustomerValueReceipt).where(CustomerValueReceipt.receipt_id == goal["receipt_id"])
    )
    goal_data = json_loads(agreement.evidence_json, {}) if agreement is not None else {}
    if goal_data.get("customer_confirmed") is not True or goal_data.get("actor_role") != "customer":
        raise ValueError("workflow delivery requires the customer's confirmed KPI agreement")
    nodes = db.scalars(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id)).all()
    edges = db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id)).all()
    ordered = _serial_employees(list(nodes), list(edges))
    common = {
        "completion_protocol": COMPLETION_PROTOCOL,
        "execution_id": int(execution.id),
        "workflow_id": int(workflow.id),
        "user_id": owner,
        "graph_fingerprint": binding["graph_fingerprint"],
        "execution_input_sha256": digest(inputs),
        "goal": goal,
        "policy": deepcopy(policy),
    }
    frozen_nodes = [_freeze_node(db, node, inputs, common) for node in ordered]
    if policy.get("employee_id") not in {node["employee_id"] for node in frozen_nodes}:
        raise ValueError("customer delivery must contain its approved primary employee")
    if len(frozen_nodes) == 1:
        return frozen_nodes[0]
    contract = {**common, "nodes": frozen_nodes}
    return {**contract, "contract_sha256": digest(contract)}


def _freeze_node(db: Any, node: Any, inputs: dict, common: dict) -> dict[str, Any]:
    from modstore_server.employee_runtime import (
        load_employee_pack_resolved,
        parse_employee_config_v2,
    )
    from modstore_server.employee_runtime_policy import apply_policy_to_config
    from modstore_server.strategic_execution_contract import (
        _pack_identity,
        freeze_execution,
    )
    from modstore_server.workflow_variables import resolve_value

    owner = common["user_id"]
    config = json_loads(node.config, {})
    employee_id, task = config.get("employee_id"), config.get("task")
    mapping = config.get("input_mapping")
    if (
        not isinstance(employee_id, str)
        or not employee_id.strip()
        or not isinstance(task, str)
        or not task.strip()
        or not isinstance(mapping, dict)
        or not mapping
        or config.get("retry_count", 0) != 0
    ):
        raise ValueError(
            "customer delivery node must match the approved employee and explicit inputs"
        )
    node_input = resolve_value(mapping, {"global": inputs, "result": inputs, "nodes": {}})
    if not node_input.get("file_path"):
        raise ValueError("customer delivery requires a deterministic native file input")
    pack = load_employee_pack_resolved(db, employee_id, user_id=owner, execute=True)
    effective, _ = apply_policy_to_config(
        employee_id, deepcopy(parse_employee_config_v2(pack.get("manifest") or {}))
    )
    actions = effective.get("actions") or {}
    nested_actions = actions.get("actions")
    if isinstance(nested_actions, dict):
        actions = nested_actions
    if actions.get("handlers") != ["direct_python"] or not pack.get("stored_filename"):
        raise ValueError("customer delivery requires one immutable native Python employee archive")
    frozen = freeze_execution(owner, {"employee_id": employee_id, "input_data": node_input})
    validated_pack = {**_pack_identity(pack), "config_sha256": digest(effective)}
    if any(frozen["execution_binding"].get(key) != value for key, value in validated_pack.items()):
        raise ValueError("native employee package changed while freezing customer delivery")
    contract = {
        **common,
        "node_id": int(node.id),
        "employee_id": employee_id,
        "task": task,
        "node_input": node_input,
        "input_data": frozen["input_data"],
        "execution_binding": frozen["execution_binding"],
        "node_config_sha256": digest(config),
    }
    return {**contract, "contract_sha256": digest(contract)}


def _stored_contract(db: Any, execution_id: int) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    execution = db.get(WorkflowExecution, execution_id, populate_existing=True)
    event = _event(db, f"{START_EVENT}:{execution_id}")
    binding = json_loads(event.payload_json, {}) if event is not None else {}
    contract = binding.get("customer_delivery") or {}
    if execution is None or not isinstance(contract, dict) or not contract:
        raise ValueError("workflow has no server-recorded customer delivery contract")
    unsigned = {key: value for key, value in contract.items() if key != "contract_sha256"}
    workflow = db.get(Workflow, execution.workflow_id, populate_existing=True)
    if (
        event.event_name != START_EVENT
        or event.aggregate_id != str(execution_id)
        or event.producer != "modstore-python"
        or (
            "completion_protocol" in contract
            and contract["completion_protocol"] != COMPLETION_PROTOCOL
        )
        or digest(unsigned) != contract.get("contract_sha256")
        or contract.get("execution_id") != execution.id
        or contract.get("user_id") != execution.user_id
        or contract.get("workflow_id") != execution.workflow_id
        or workflow is None
        or workflow.user_id != execution.user_id
        or digest(json_loads(execution.input_data, None)) != contract.get("execution_input_sha256")
        or workflow_graph_fingerprint(db, execution.workflow_id)
        != contract.get("graph_fingerprint")
        or binding.get("user_id") != execution.user_id
        or binding.get("execution_id") != execution.id
        or binding.get("execution_allowed") is not True
    ):
        raise ValueError("workflow customer delivery contract no longer matches its execution")
    _customer(db, int(execution.user_id))
    return execution, binding, contract


def require_running_contract(contract: dict[str, Any]) -> None:
    """Recheck SQL authority at every existing native execution boundary."""
    from modstore_server.workflow_execution_feedback import _admitted

    with get_session_factory()() as db:
        execution, binding, stored = _stored_contract(db, int(contract["execution_id"]))
        if (
            execution.status != "running"
            or delivery_node(stored, contract["node_id"]) != contract
            or not (_admitted(db, binding) or _admitted(db, binding, promoted=True))
        ):
            raise ValueError("workflow customer delivery approval is no longer current")
        current = prepare_customer_delivery(db, execution, binding, contract["policy"])
        if current != stored:
            raise ValueError("workflow customer delivery inputs, package or agreement changed")


def read_artifact_bytes(contract: dict[str, Any], artifact: dict[str, Any]) -> tuple[bytes, str]:
    from modstore_server.integrations.vibe_adapter import ensure_within_workspace

    root = ensure_within_workspace(
        contract["input_data"]["project_root"], user_id=contract["user_id"]
    )
    relative = Path(str(artifact["output_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("workflow delivery path is not relative to the original workspace")
    path = ensure_within_workspace(root / relative, user_id=contract["user_id"])
    path.relative_to(root)
    if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("workflow delivery file is unavailable")
    with path.open("rb") as stream:
        content = stream.read(MAX_ARTIFACT_BYTES + 1)
    if (
        len(content) > MAX_ARTIFACT_BYTES
        or len(content) != artifact["size_bytes"]
        or hashlib.sha256(content).hexdigest() != artifact["artifact_sha256"]
    ):
        raise ValueError("workflow delivery file bytes changed")
    return content, path.name


def _native_artifacts(
    contract: dict[str, Any], result: Any, *, verify_files: bool = True
) -> list[dict[str, Any]]:
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt

    if evaluate_execution_receipt(result).status != "completed":
        raise ValueError("native customer delivery has no verified terminal receipt")
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    outputs = payload.get("outputs") or []
    if len(outputs) != 1 or outputs[0].get("handler") != "direct_python":
        raise ValueError("customer delivery was not produced by its original native handler")
    rows = (outputs[0].get("output") or {}).get("artifacts") or []
    artifacts = []
    for row in rows:
        artifact = {
            "artifact_id": f"workflow-file-{contract['execution_id']}-{contract['node_id']}-"
            + digest(row["path"])[:24],
            "artifact_sha256": row["artifact_sha256"],
            "output_path": row["path"],
            "size_bytes": row["size_bytes"],
            "source": ARTIFACT_SOURCE,
        }
        if verify_files:
            read_artifact_bytes(contract, artifact)
        artifacts.append(artifact)
    if not artifacts or len({row["artifact_id"] for row in artifacts}) != len(artifacts):
        raise ValueError("native customer delivery has no unique verified output files")
    return artifacts


def run_customer_delivery_node(
    *,
    execution_id: int,
    node_id: int,
    user_id: int,
    config: dict[str, Any],
    node_input: dict[str, Any],
    execute: Callable[..., dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None]:
    """Claim once, invoke the real native consumer, and persist only its verified bytes."""
    from modstore_server.strategic_execution_contract import workflow_execution_scope

    with get_session_factory()() as db:
        event = _event(db, f"{START_EVENT}:{execution_id}")
        binding = json_loads(event.payload_json, {}) if event is not None else {}
        if not binding.get("customer_delivery"):
            return False, None
        _execution, _binding, graph = _stored_contract(db, execution_id)
        contract = delivery_node(graph, node_id)
        if (
            contract["node_id"] != node_id
            or contract["user_id"] != user_id
            or contract["node_config_sha256"] != digest(config)
            or contract["node_input"] != node_input
        ):
            raise ValueError("native customer node differs from the original execution contract")
        require_running_contract(contract)
        for preceding in delivery_nodes(graph):
            if preceding["node_id"] == node_id:
                break
            load_produced_delivery(db, preceding)
        identity = f"{execution_id}:{node_id}"
        if (
            enqueue(
                db,
                CLAIM_EVENT,
                str(execution_id),
                {
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "contract_sha256": contract["contract_sha256"],
                },
                event_id=f"{CLAIM_EVENT}:{identity}",
            )
            is None
        ):
            raise ValueError("native customer delivery already started; replay is not permitted")
        db.commit()
    with workflow_execution_scope(contract):
        result = execute(
            employee_id=contract["employee_id"],
            task=contract["task"],
            input_data=deepcopy(contract["input_data"]),
            user_id=user_id,
        )
        artifacts = _native_artifacts(contract, result)
    # Native completion alone is not customer acceptance or a completed workflow.
    with get_session_factory()() as db:
        _execution, _binding, current = _stored_contract(db, execution_id)
        if current != graph:
            raise ValueError("workflow contract changed before recording native delivery")
        enqueue(
            db,
            PRODUCED_EVENT,
            str(execution_id),
            {
                **{
                    key: contract[key]
                    for key in (
                        "execution_id",
                        "workflow_id",
                        "user_id",
                        "node_id",
                        "contract_sha256",
                    )
                },
                "artifacts": artifacts,
                "completion_protocol": COMPLETION_PROTOCOL,
                "native_result_sha256": digest(result),
                "completed_at": datetime.now(UTC).isoformat(),
            },
            event_id=f"{PRODUCED_EVENT}:{identity}",
        )
        db.commit()
    return True, result


def load_completed_delivery(db: Any, execution_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read sealed completion facts; later workspace files cannot erase history.

    Download/acceptance and unfinished graph finalization separately require
    the current file bytes. Historical observations retain the original receipt.
    """
    from modstore_server.workflow_customer_finalization import (
        RETURNED_EVENT,
        _legacy_completed_return,
        _load_return,
        _original_delivery,
        _utc,
    )

    execution, binding, contract = _stored_contract(db, execution_id)
    if execution.status != "completed" or execution.completed_at is None:
        raise ValueError("workflow customer delivery has not actually completed")
    produced = load_produced_delivery(db, contract, verify_files=False)
    returned = (
        _load_return(db, execution_id)
        if _event(db, f"{RETURNED_EVENT}:{execution_id}") is not None
        else _legacy_completed_return(db, execution, binding, contract, produced)
    )
    _original_delivery(db, returned, verify_files=False)
    if (
        execution.output_data != returned.output_json
        or execution.error_message not in (None, "")
        or _utc(execution.completed_at) != _utc(returned.completed_at)
    ):
        raise ValueError("workflow customer completion differs from its original graph return")
    return binding, produced


def load_produced_delivery(
    db: Any, contract: dict[str, Any], *, verify_files: bool = True
) -> dict[str, Any]:
    """Require every original node receipt; no PRODUCED subset implies graph success."""
    rows: list[dict[str, Any]] = []
    paths = set()
    for node in delivery_nodes(contract):
        identity = {
            key: node[key]
            for key in (
                "execution_id",
                "workflow_id",
                "user_id",
                "node_id",
                "contract_sha256",
            )
        }
        records = {}
        for name in (CLAIM_EVENT, PRODUCED_EVENT):
            event = _event(db, f"{name}:{node['execution_id']}:{node['node_id']}")
            if (
                event is None
                or event.event_name != name
                or event.aggregate_id != str(node["execution_id"])
                or event.producer != "modstore-python"
            ):
                raise ValueError("customer delivery has no original node receipt")
            records[name] = json_loads(event.payload_json, {})
        if records[CLAIM_EVENT] != {
            key: identity[key] for key in ("execution_id", "node_id", "contract_sha256")
        }:
            raise ValueError("customer delivery node claim changed")
        produced = records[PRODUCED_EVENT]
        if (
            any(produced.get(key) != value for key, value in identity.items())
            or (
                ("completion_protocol" in node or "completion_protocol" in produced)
                and (
                    node.get("completion_protocol") != COMPLETION_PROTOCOL
                    or produced.get("completion_protocol") != COMPLETION_PROTOCOL
                )
            )
            or not isinstance(produced.get("artifacts"), list)
            or not produced["artifacts"]
        ):
            raise ValueError("customer delivery node result changed")
        for artifact in produced["artifacts"]:
            expected = (
                f"workflow-file-{node['execution_id']}-{node['node_id']}-"
                + digest(artifact["output_path"])[:24]
            )
            path = str(
                (Path(node["input_data"]["project_root"]) / artifact["output_path"]).resolve()
            )
            if (
                artifact.get("artifact_id") != expected
                or artifact.get("source") != ARTIFACT_SOURCE
                or path in paths
            ):
                raise ValueError("customer delivery artifact identity changed or was reused")
            if verify_files:
                read_artifact_bytes(node, artifact)
            paths.add(path)
        rows.append(produced)
    if len(rows) == 1:
        return rows[0]
    return {
        **{
            key: contract[key]
            for key in ("execution_id", "workflow_id", "user_id", "contract_sha256")
        },
        "nodes": rows,
        "artifacts": [artifact for row in rows for artifact in row["artifacts"]],
        "completed_at": max(row["completed_at"] for row in rows),
    }
