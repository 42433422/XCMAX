"""Script delivery for workbench delivery."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, cast

from sqlalchemy.orm import Session

from modstore_server.models import (
    ScriptWorkflow,
    ScriptWorkflowRun,
    ScriptWorkflowVersion,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.planning import _script_workflow_brief


class ScriptWorkflowRecord(Protocol):
    updated_at: datetime


_LOG = logging.getLogger("modstore_server.workbench_api")


def _embed_script_workflow_in_employee_pack(
    pack_dir: Path,
    *,
    script_workflow: Dict[str, Any],
    brief: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Write ScriptWorkflow linkage into an employee pack manifest in-place.

    When *db* is supplied the function also embeds a portable
    ``script_workflow_bundles`` entry so the pack is self-contained and can be
    installed into a different environment without losing the script definition.
    """
    mf = pack_dir / "manifest.json"
    if not mf.is_file():
        raise FileNotFoundError(f"embed_script: manifest.json 不存在：{mf}")
    try:
        raw = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"embed_script: manifest.json 解析失败（{mf}）：{exc}"
        ) from exc
    v2 = (
        cast(dict[str, Any], raw.get("employee_config_v2"))
        if isinstance(raw.get("employee_config_v2"), dict)
        else {}
    )
    collab = (
        cast(dict[str, Any], v2.get("collaboration"))
        if isinstance(v2.get("collaboration"), dict)
        else {}
    )
    entries = collab.get("script_workflows")
    if not isinstance(entries, list):
        entries = []
    sid = script_workflow.get("id")
    sid_int = int(sid) if sid is not None else 0
    entry = {
        "script_workflow_id": sid_int,
        "workflow_id": sid_int,
        "name": str(script_workflow.get("name") or "员工脚本工作流"),
        "trigger_type": "manual",
        "role": "primary_program",
        "description": (brief or "").strip()[:1000],
    }
    deduped: List[Any] = []
    for x in entries:
        if not isinstance(x, dict):
            deduped.append(x)
            continue
        try:
            existing_id = int(x.get("script_workflow_id") or x.get("workflow_id") or 0)
        except (TypeError, ValueError):
            existing_id = 0
        if existing_id != sid_int:
            deduped.append(x)
    entries = deduped
    entries.insert(0, entry)
    collab = {**collab, "script_workflows": entries}
    v2["collaboration"] = collab
    raw["employee_config_v2"] = v2
    raw["script_workflow_attachment"] = {
        "script_workflow_id": sid_int,
        "name": entry["name"],
        "trigger_type": entry["trigger_type"],
    }
    if db is not None and sid_int > 0:
        try:
            from modstore_server.employee_pack_workflow_bundle import (
                embed_workflow_bundles_in_manifest,
            )

            embed_workflow_bundles_in_manifest(db, raw)
        except RECOVERABLE_ERRORS as _e:
            _LOG.warning("embed script workflow bundle failed sid=%d: %s", sid_int, _e)
    _pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    if isinstance(raw.get("employee"), dict):
        raw["employee"]["id"] = _pack_id
    for _wf_row in raw.get("workflow_employees") or []:
        if isinstance(_wf_row, dict):
            _wf_row["id"] = _pack_id
    mf.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return cast(dict[str, Any], raw["script_workflow_attachment"])


def _commit_script_workflow_from_result(
    db: Session,
    *,
    user_id: int,
    session_id: str,
    payload: Dict[str, Any],
    files: List[Dict[str, Any]],
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """把工作台的一次性脚本结果保存为可继续沙箱调试的脚本工作流。"""
    code = str(result.get("script") or "").strip()
    if not result.get("ok") or not code:
        _LOG.warning(
            "commit_script_workflow: skip — ok=%s script_len=%d errors=%s session=%s",
            result.get("ok"),
            len(code),
            result.get("errors"),
            session_id,
        )
        return None
    raw_name = str(payload.get("workflow_name") or "").strip()
    if not raw_name:
        raw_name = str(payload.get("brief") or "").strip()[:40] or "Excel 文件处理"
    name = raw_name if raw_name.endswith("脚本工作流") else f"{raw_name} 脚本工作流"
    brief_json = _script_workflow_brief(payload, files)
    wf = ScriptWorkflow(
        user_id=user_id,
        name=name[:256],
        brief_json=json.dumps(brief_json, ensure_ascii=False),
        script_text=code,
        schema_in_json=json.dumps({}, ensure_ascii=False),
        status="sandbox_testing",
        agent_session_id=session_id,
    )
    db.add(wf)
    db.flush()
    version = ScriptWorkflowVersion(
        workflow_id=wf.id,
        version_no=1,
        script_text=code,
        plan_md="由工作台附件生成的初始脚本工作流。",
        agent_log_json=json.dumps(
            {"source": "workbench", "session_id": session_id}, ensure_ascii=False
        ),
        is_current=True,
    )
    db.add(version)
    db.flush()
    run = ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=version.id,
        user_id=user_id,
        mode="auto",
        status="success",
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
        outputs_meta_json=json.dumps(result.get("outputs") or [], ensure_ascii=False),
        runtime_sdk_calls_json=json.dumps(
            result.get("sdk_calls") or [], ensure_ascii=False
        ),
        error_message="",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    cast(ScriptWorkflowRecord, wf).updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wf)
    return {"id": wf.id, "name": wf.name}
