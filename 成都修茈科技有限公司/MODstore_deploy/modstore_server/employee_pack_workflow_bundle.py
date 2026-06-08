"""Portable workflow/script-workflow bundling for employee packs.

Packs normally only carry *references* (integer IDs) to workflows and
script-workflows. Those IDs are valid only in the originating database; after
copying a ``.xcemp`` to another environment the IDs are dangling.

This module provides:

* :func:`export_workflow_bundle`           – DB row → portable dict (no IDs)
* :func:`export_script_workflow_bundle`    – DB row → portable dict
* :func:`embed_workflow_bundles_in_manifest` – convenience: resolve all
  referenced IDs from the current DB and write bundles into the manifest dict
  (in-place)
* :func:`rehydrate_workflow_bundles`       – on install in a *target* DB:
  create new rows from the embedded bundles, then rewrite manifest ID
  references so the pack is immediately usable
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modstore_server.models import (
    ScriptWorkflow,
    ScriptWorkflowVersion,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


# ── Serialisation ────────────────────────────────────────────────────────────


def export_workflow_bundle(db: Session, workflow_id: int) -> Optional[Dict[str, Any]]:
    """Return a portable representation of a canvas Workflow (nodes + edges).

    The returned dict uses *temporary* node keys (``n0``, ``n1``, …) in place
    of DB integer IDs so the bundle is self-contained and can be inserted into
    any database without conflicts.

    Returns ``None`` when the workflow_id does not exist in the DB.
    """
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        return None

    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow_id)
        .order_by(WorkflowNode.id)
        .all()
    )
    edges = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == workflow_id)
        .order_by(WorkflowEdge.id)
        .all()
    )

    # Map original DB node IDs → stable temp keys inside the bundle
    node_key_map: Dict[int, str] = {n.id: f"n{i}" for i, n in enumerate(nodes)}

    nodes_out = []
    for n in nodes:
        try:
            cfg = json.loads(n.config or "{}")
        except (ValueError, TypeError):
            cfg = {}
        nodes_out.append(
            {
                "node_key": node_key_map[n.id],
                "node_type": n.node_type,
                "name": n.name,
                "config": cfg,
                "position_x": float(n.position_x or 0.0),
                "position_y": float(n.position_y or 0.0),
            }
        )

    edges_out = []
    for e in edges:
        src_key = node_key_map.get(e.source_node_id)
        tgt_key = node_key_map.get(e.target_node_id)
        if src_key is None or tgt_key is None:
            # Skip dangling edges (orphaned after node deletion)
            continue
        edges_out.append(
            {
                "source_node_key": src_key,
                "target_node_key": tgt_key,
                "condition": e.condition or "",
            }
        )

    return {
        "source_workflow_id": workflow_id,
        "name": wf.name,
        "description": wf.description or "",
        "kind": wf.kind or "",
        "nodes": nodes_out,
        "edges": edges_out,
    }


def export_script_workflow_bundle(db: Session, script_workflow_id: int) -> Optional[Dict[str, Any]]:
    """Return a portable representation of a ScriptWorkflow with its current version."""
    swf = db.query(ScriptWorkflow).filter(ScriptWorkflow.id == script_workflow_id).first()
    if not swf:
        return None

    cur_ver = (
        db.query(ScriptWorkflowVersion)
        .filter(
            ScriptWorkflowVersion.workflow_id == script_workflow_id,
            ScriptWorkflowVersion.is_current.is_(True),
        )
        .order_by(ScriptWorkflowVersion.version_no.desc())
        .first()
    )

    try:
        brief_json = json.loads(swf.brief_json or "{}")
    except (ValueError, TypeError):
        brief_json = {}
    try:
        schema_in = json.loads(swf.schema_in_json or "{}")
    except (ValueError, TypeError):
        schema_in = {}

    current_version: Dict[str, Any] = {}
    if cur_ver:
        try:
            agent_log = json.loads(cur_ver.agent_log_json or "{}")
        except (ValueError, TypeError):
            agent_log = {}
        current_version = {
            "script_text": cur_ver.script_text or "",
            "plan_md": cur_ver.plan_md or "",
            "agent_log_json": agent_log,
        }

    return {
        "source_script_workflow_id": script_workflow_id,
        "name": swf.name,
        "brief_json": brief_json,
        "schema_in_json": schema_in,
        "status": swf.status or "draft",
        "current_version": current_version,
    }


# ── Embed into manifest ───────────────────────────────────────────────────────


def _collect_referenced_ids(
    manifest: Dict[str, Any],
) -> Tuple[List[int], List[int]]:
    """Walk a manifest and return (workflow_ids, script_workflow_ids)."""
    wf_ids: List[int] = []
    swf_ids: List[int] = []

    def _add_wf(val: Any) -> None:
        try:
            v = int(val or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0 and v not in wf_ids:
            wf_ids.append(v)

    def _add_swf(val: Any) -> None:
        try:
            v = int(val or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0 and v not in swf_ids:
            swf_ids.append(v)

    for row in manifest.get("workflow_employees") or []:
        if isinstance(row, dict):
            _add_wf(row.get("workflow_id") or row.get("workflowId"))

    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}

    wf_entry = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
    _add_wf(wf_entry.get("workflow_id") or wf_entry.get("workflowId"))

    for entry in collab.get("script_workflows") or []:
        if isinstance(entry, dict):
            _add_swf(entry.get("script_workflow_id") or entry.get("workflow_id"))

    swa = manifest.get("script_workflow_attachment")
    if isinstance(swa, dict):
        _add_swf(swa.get("script_workflow_id") or swa.get("workflow_id"))

    wa = manifest.get("workflow_attachment")
    if isinstance(wa, dict):
        _add_wf(wa.get("workflow_id"))

    return wf_ids, swf_ids


def embed_workflow_bundles_in_manifest(
    db: Session,
    manifest: Dict[str, Any],
    *,
    skip_missing: bool = True,
) -> Dict[str, Any]:
    """Resolve all workflow/script_workflow references in *manifest* and embed
    portable bundle definitions in-place.

    Returns the mutated manifest (same object).

    When ``skip_missing=True`` (default), IDs that are not found in the DB are
    silently skipped; set to ``False`` to raise on the first missing ID.
    """
    wf_ids, swf_ids = _collect_referenced_ids(manifest)

    # Index existing bundles so we don't duplicate on repeated calls
    existing_wf_ids = {
        b["source_workflow_id"]
        for b in (manifest.get("workflow_bundles") or [])
        if isinstance(b, dict) and b.get("source_workflow_id")
    }
    existing_swf_ids = {
        b["source_script_workflow_id"]
        for b in (manifest.get("script_workflow_bundles") or [])
        if isinstance(b, dict) and b.get("source_script_workflow_id")
    }

    wf_bundles: List[Dict[str, Any]] = list(manifest.get("workflow_bundles") or [])
    swf_bundles: List[Dict[str, Any]] = list(manifest.get("script_workflow_bundles") or [])

    for wid in wf_ids:
        if wid in existing_wf_ids:
            continue
        bundle = export_workflow_bundle(db, wid)
        if bundle is None:
            if not skip_missing:
                raise ValueError(f"workflow_id={wid} not found in DB")
            logger.warning("embed_workflow_bundles: workflow_id=%d not found, skipped", wid)
            continue
        wf_bundles.append(bundle)
        existing_wf_ids.add(wid)

    for sid in swf_ids:
        if sid in existing_swf_ids:
            continue
        bundle = export_script_workflow_bundle(db, sid)
        if bundle is None:
            if not skip_missing:
                raise ValueError(f"script_workflow_id={sid} not found in DB")
            logger.warning("embed_workflow_bundles: script_workflow_id=%d not found, skipped", sid)
            continue
        swf_bundles.append(bundle)
        existing_swf_ids.add(sid)

    if wf_bundles:
        manifest["workflow_bundles"] = wf_bundles
    if swf_bundles:
        manifest["script_workflow_bundles"] = swf_bundles

    # Update the metadata note to reflect bundled mode
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    meta = v2.get("metadata") if isinstance(v2.get("metadata"), dict) else {}
    meta["workflow_runtime_check"] = (
        "employee_pack 已内嵌 workflow_bundles / script_workflow_bundles；"
        "安装时会自动在目标库重建并回写 ID。"
    )
    v2["metadata"] = meta
    manifest["employee_config_v2"] = v2

    return manifest


# ── Rehydration on install ────────────────────────────────────────────────────


def _create_workflow_from_bundle(db: Session, user: User, bundle: Dict[str, Any]) -> int:
    """Insert a Workflow + nodes + edges from a bundle dict; return new workflow ID."""
    wf = Workflow(
        user_id=user.id,
        name=bundle.get("name") or "bundled-workflow",
        description=bundle.get("description") or "",
        kind=bundle.get("kind") or "",
        is_active=True,
    )
    db.add(wf)
    db.flush()

    # node_key → newly created DB node ID
    key_to_id: Dict[str, int] = {}
    for node_def in bundle.get("nodes") or []:
        try:
            cfg_text = json.dumps(node_def.get("config") or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            cfg_text = "{}"
        n = WorkflowNode(
            workflow_id=wf.id,
            node_type=node_def.get("node_type") or "unknown",
            name=node_def.get("name") or "",
            config=cfg_text,
            position_x=float(node_def.get("position_x") or 0.0),
            position_y=float(node_def.get("position_y") or 0.0),
        )
        db.add(n)
        db.flush()
        key = node_def.get("node_key") or str(n.id)
        key_to_id[key] = n.id

    for edge_def in bundle.get("edges") or []:
        src_id = key_to_id.get(edge_def.get("source_node_key") or "")
        tgt_id = key_to_id.get(edge_def.get("target_node_key") or "")
        if src_id is None or tgt_id is None:
            continue
        e = WorkflowEdge(
            workflow_id=wf.id,
            source_node_id=src_id,
            target_node_id=tgt_id,
            condition=edge_def.get("condition") or "",
        )
        db.add(e)

    db.flush()
    return int(wf.id)


def _create_script_workflow_from_bundle(db: Session, user: User, bundle: Dict[str, Any]) -> int:
    """Insert a ScriptWorkflow + current version from a bundle dict; return new ID."""
    try:
        brief_text = json.dumps(bundle.get("brief_json") or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        brief_text = "{}"
    try:
        schema_text = json.dumps(bundle.get("schema_in_json") or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        schema_text = "{}"

    swf = ScriptWorkflow(
        user_id=user.id,
        name=bundle.get("name") or "bundled-script-workflow",
        brief_json=brief_text,
        schema_in_json=schema_text,
        status=bundle.get("status") or "draft",
    )
    db.add(swf)
    db.flush()

    cv = bundle.get("current_version") or {}
    if cv:
        try:
            al_text = json.dumps(cv.get("agent_log_json") or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            al_text = "{}"
        ver = ScriptWorkflowVersion(
            workflow_id=swf.id,
            version_no=1,
            script_text=cv.get("script_text") or "",
            plan_md=cv.get("plan_md") or "",
            agent_log_json=al_text,
            is_current=True,
        )
        db.add(ver)
        db.flush()

    return int(swf.id)


def rehydrate_workflow_bundles(
    db: Session,
    user: User,
    manifest: Dict[str, Any],
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Create DB rows from embedded bundles and rewrite manifest ID references.

    Idempotent: if a bundle's ``source_*_id`` has already been rehydrated
    (detected by the presence of a ``rehydrated_workflow_id`` marker on the
    bundle), the creation step is skipped.

    Returns the mutated manifest (same object).
    """
    wf_bundles: List[Dict[str, Any]] = [
        b for b in (manifest.get("workflow_bundles") or []) if isinstance(b, dict)
    ]
    swf_bundles: List[Dict[str, Any]] = [
        b for b in (manifest.get("script_workflow_bundles") or []) if isinstance(b, dict)
    ]

    if not wf_bundles and not swf_bundles:
        return manifest

    # Build source → new-target ID maps
    wf_id_map: Dict[int, int] = {}  # source_workflow_id → new_workflow_id
    swf_id_map: Dict[int, int] = {}  # source_script_workflow_id → new_script_workflow_id

    for bundle in wf_bundles:
        src_id = bundle.get("source_workflow_id")
        if not src_id:
            continue
        if bundle.get("rehydrated_workflow_id"):
            # Already rehydrated in a previous call; honour the existing mapping
            wf_id_map[int(src_id)] = int(bundle["rehydrated_workflow_id"])
            continue
        new_id = _create_workflow_from_bundle(db, user, bundle)
        bundle["rehydrated_workflow_id"] = new_id
        wf_id_map[int(src_id)] = new_id

    for bundle in swf_bundles:
        src_id = bundle.get("source_script_workflow_id")
        if not src_id:
            continue
        if bundle.get("rehydrated_script_workflow_id"):
            swf_id_map[int(src_id)] = int(bundle["rehydrated_script_workflow_id"])
            continue
        new_id = _create_script_workflow_from_bundle(db, user, bundle)
        bundle["rehydrated_script_workflow_id"] = new_id
        swf_id_map[int(src_id)] = new_id

    if commit:
        db.commit()

    if not wf_id_map and not swf_id_map:
        return manifest

    # ── Rewrite manifest references ──────────────────────────────────────────
    def _remap_wf(val: Any) -> Any:
        try:
            v = int(val or 0)
        except (TypeError, ValueError):
            return val
        return wf_id_map.get(v, v) if v > 0 else val

    def _remap_swf(val: Any) -> Any:
        try:
            v = int(val or 0)
        except (TypeError, ValueError):
            return val
        return swf_id_map.get(v, v) if v > 0 else val

    # workflow_employees[*].workflow_id
    for row in manifest.get("workflow_employees") or []:
        if not isinstance(row, dict):
            continue
        for key in ("workflow_id", "workflowId"):
            if key in row:
                row[key] = _remap_wf(row[key])

    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}

    # employee_config_v2.collaboration.workflow.workflow_id
    wf_entry = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
    for key in ("workflow_id", "workflowId"):
        if key in wf_entry:
            wf_entry[key] = _remap_wf(wf_entry[key])
    if wf_entry:
        collab["workflow"] = wf_entry

    # employee_config_v2.collaboration.script_workflows[*]
    for entry in collab.get("script_workflows") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("script_workflow_id", "workflow_id"):
            if key in entry:
                entry[key] = _remap_swf(entry[key])

    v2["collaboration"] = collab
    manifest["employee_config_v2"] = v2

    # script_workflow_attachment
    swa = manifest.get("script_workflow_attachment")
    if isinstance(swa, dict):
        for key in ("script_workflow_id", "workflow_id"):
            if key in swa:
                swa[key] = _remap_swf(swa[key])

    # workflow_attachment
    wa = manifest.get("workflow_attachment")
    if isinstance(wa, dict):
        if "workflow_id" in wa:
            wa["workflow_id"] = _remap_wf(wa["workflow_id"])

    # Update the bundles list in the manifest (they now carry rehydrated IDs)
    if wf_bundles:
        manifest["workflow_bundles"] = wf_bundles
    if swf_bundles:
        manifest["script_workflow_bundles"] = swf_bundles

    return manifest
