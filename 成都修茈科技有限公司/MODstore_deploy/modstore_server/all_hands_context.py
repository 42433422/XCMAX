"""Read employee metadata and build role-specific, grounded meeting context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from sqlalchemy.orm import Session

from modstore_server.all_hands_ports import JsonObject, SessionProvider
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _snapshot_employee_cron_overview(limit: int = 24) -> List[Dict[str, Any]]:
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        jobs = list_employee_cron_jobs() or []
    except RECOVERABLE_ERRORS as exc:
        logger.debug("all_hands: cron overview failed error_type=%s", type(exc).__name__)
        return []
    out: List[Dict[str, Any]] = []
    for row in jobs[: max(1, min(limit, 40))]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "employee_id": str(row.get("employee_id") or row.get("id") or ""),
                "next_run_time": str(row.get("next_run_time") or ""),
                "trigger": str(row.get("trigger") or "")[:120],
            }
        )
    return out


@dataclass(frozen=True)
class AllHandsContext:
    session_provider: SessionProvider
    pack_loader: Callable[[Session, str], JsonObject]
    area_for: Callable[[str], str | None]
    metadata: Callable[[str], JsonObject]
    pending_changes: Callable[[], list[JsonObject]]
    cron_overview: Callable[[], list[JsonObject]]
    craft_ids: frozenset[str]

    def load_metadata(self, pkg_id: str) -> Dict[str, Any]:
        """读取 yuangon/<area>/<pkg_id>/employee.yaml 中的 owner/area/domain 等元数据。"""
        from modstore_server.daily_employee_briefs import _resolve_pack_dir

        area = self.area_for(pkg_id) or ""
        if not area:
            return {}
        _root, pack_dir = _resolve_pack_dir(area, pkg_id)
        yaml_path = pack_dir / "employee.yaml"
        if not yaml_path.is_file():
            return {"area": area}
        try:
            import yaml

            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except RECOVERABLE_ERRORS as exc:
            logger.debug("all_hands: employee.yaml read failed error_type=%s", type(exc).__name__)
            return {"area": area}
        if not isinstance(data, dict):
            return {"area": area}
        meta: Dict[str, Any] = {"area": str(data.get("area") or area).strip()}
        for key in ("owner", "domain", "id", "name", "version"):
            val = data.get(key)
            if val is not None and str(val).strip():
                meta[key] = str(val).strip()
        sla = data.get("sla")
        if isinstance(sla, dict):
            meta["sla"] = sla
        trig = data.get("triggers")
        if isinstance(trig, dict):
            meta["triggers"] = trig
        deps = data.get("depends_on")
        if isinstance(deps, list):
            meta["depends_on_yaml"] = [str(x).strip() for x in deps if str(x).strip()][:8]
        bc = data.get("business_context")
        if isinstance(bc, dict) and bc:
            meta["business_context"] = bc
        ci_paths = data.get("ci_coverage_artifacts")
        if isinstance(ci_paths, list) and ci_paths:
            meta["ci_coverage_artifacts"] = [str(x).strip() for x in ci_paths if str(x).strip()][
                :12
            ]
        return meta

    def manifest_signals(self, pkg_id: str) -> Dict[str, Any]:
        """从员工包 manifest 抽取汇报 grounding 字段（identity/role/handlers/depends_on/behavior_rules）。"""
        out: Dict[str, Any] = {
            "name": pkg_id,
            "description": "",
            "persona": "",
            "expertise": [],
            "handlers": [],
            "depends_on": [],
            "skills": [],
            "behavior_rules": [],
            "workflow_id": 0,
            "owner": "",
            "area": "",
            "domain": "",
            "employee_config_v2_outline": {},
        }
        yuangon_meta = self.metadata(pkg_id)
        out["owner"] = str(yuangon_meta.get("owner") or "")
        out["area"] = str(yuangon_meta.get("area") or self.area_for(pkg_id) or "")
        out["domain"] = str(yuangon_meta.get("domain") or "")
        try:
            sf = self.session_provider()
            with sf() as session:
                pack = self.pack_loader(session, pkg_id)
            raw_manifest = pack.get("manifest")
            man = raw_manifest if isinstance(raw_manifest, dict) else {}
            v2 = man.get("employee_config_v2")
            if not isinstance(v2, dict):
                raise ValueError("employee_config_v2 must be an object")
            ident = v2.get("identity") or {}
            cog = v2.get("cognition") or {}
            agent = cog.get("agent") or {}
            role = agent.get("role") or {}
            actions = v2.get("actions") or {}
            collab = v2.get("collaboration") or {}
            wf = collab.get("workflow") or {}
            out["name"] = str(ident.get("name") or man.get("name") or pkg_id)
            out["description"] = str(ident.get("description") or man.get("description") or "")[:280]
            out["persona"] = str(role.get("persona") or agent.get("system_prompt") or "")[:400]
            sp = str(agent.get("system_prompt") or "").strip()
            out["system_prompt_present"] = bool(sp)
            out["system_prompt_chars"] = len(sp)
            if sp and (not out["persona"]):
                out["persona"] = sp[:400]
            if isinstance(role.get("expertise"), list):
                out["expertise"] = [str(x) for x in role["expertise"] if str(x).strip()][:8]
            if isinstance(actions.get("handlers"), list):
                out["handlers"] = [str(x) for x in actions["handlers"] if str(x).strip()][:12]
            if isinstance(cog.get("skills"), list):
                for s in cog["skills"][:6]:
                    if isinstance(s, dict) and s.get("name"):
                        out["skills"].append(
                            {
                                "name": str(s.get("name"))[:48],
                                "brief": str(s.get("brief") or s.get("description") or "")[:160],
                                "kind": str(s.get("kind") or "")[:32],
                            }
                        )
            if isinstance(agent.get("behavior_rules"), list):
                for rule in agent["behavior_rules"]:
                    if len(out["behavior_rules"]) >= 8:
                        break
                    text = ""
                    if isinstance(rule, str):
                        text = rule.strip()
                    elif isinstance(rule, dict):
                        name = str(rule.get("name") or rule.get("rule_id") or "").strip()
                        desc = str(rule.get("description") or rule.get("text") or "").strip()
                        if name and desc:
                            text = f"{name}: {desc}"
                        else:
                            text = name or desc
                    if text:
                        if len(text) > 120:
                            text = text[:117].rstrip() + "…"
                        out["behavior_rules"].append(text)
            deps_raw = collab.get("depends_on")
            if not isinstance(deps_raw, list):
                deps_raw = man.get("depends_on") if isinstance(man, dict) else None
            if isinstance(deps_raw, list):
                out["depends_on"] = [str(x) for x in deps_raw if str(x).strip()][:8]
            raw_policy = v2.get("workspace_policy")
            wp = raw_policy if isinstance(raw_policy, dict) else {}
            raw_scope = wp.get("scope_globs")
            scope_globs = raw_scope if isinstance(raw_scope, list) else []
            raw_forbidden = wp.get("forbidden_globs")
            forbidden_globs = raw_forbidden if isinstance(raw_forbidden, list) else []
            raw_identity = v2.get("identity")
            ident_block = raw_identity if isinstance(raw_identity, dict) else {}
            if not out["owner"] and ident_block.get("owner"):
                out["owner"] = str(ident_block.get("owner") or "").strip()
            if not out["area"] and ident_block.get("area"):
                out["area"] = str(ident_block.get("area") or "").strip()
            out["employee_config_v2_outline"] = {
                "identity_id": str(ident_block.get("id") or pkg_id),
                "artifact": str(ident_block.get("artifact") or "employee_pack"),
                "handlers": list(out["handlers"]),
                "depends_on": list(out["depends_on"]),
                "workspace_scope_globs": [str(x) for x in scope_globs if str(x).strip()][:6],
                "workspace_forbidden_globs": [str(x) for x in forbidden_globs if str(x).strip()][
                    :4
                ],
                "skills_count": len(out["skills"]),
                "behavior_rules_count": len(out["behavior_rules"]),
            }
            try:
                out["workflow_id"] = int(wf.get("workflow_id") or 0)
            except (TypeError, ValueError):
                out["workflow_id"] = 0
            raw_signals = v2.get("manifest_signals")
            sig_block = raw_signals if isinstance(raw_signals, dict) else {}
            ci_art = sig_block.get("ci_coverage_artifacts")
            if isinstance(ci_art, list) and ci_art:
                out["ci_coverage_artifacts"] = [str(x).strip() for x in ci_art if str(x).strip()][
                    :12
                ]
        except RECOVERABLE_ERRORS as exc:
            logger.debug("all_hands: manifest read failed error_type=%s", type(exc).__name__)
        if "ci_coverage_artifacts" not in out:
            yg_ci = yuangon_meta.get("ci_coverage_artifacts")
            if isinstance(yg_ci, list) and yg_ci:
                out["ci_coverage_artifacts"] = [str(x).strip() for x in yg_ci if str(x).strip()][
                    :12
                ]
        bc = yuangon_meta.get("business_context")
        if isinstance(bc, dict) and bc:
            out["business_context"] = bc
        return out

    def role_context(self, pkg_id: str) -> Dict[str, Any]:
        """按岗位注入员工大会专用上下文，避免「缺 Change ID / 缺调度清单」类空答。"""
        ctx: Dict[str, Any] = {"mode": "all_hands_meeting"}
        if pkg_id == "change-request-auditor":
            pending = self.pending_changes()
            ctx["pending_change_requests"] = pending
            ctx["instruction"] = (
                "若 pending_change_requests 非空：逐条引用 id / source_employee_id / diff_summary 说明评审要点；若为空：说明当前无待审变更，并列出 manifest 中的评审流程与 depends_on。"
            )
        elif pkg_id == "daily-orchestrator":
            ctx["employee_cron_overview"] = self.cron_overview()
            ctx["instruction"] = (
                "结合 employee_cron_overview 说明当前定时任务覆盖与缺口；无记录时依据 manifest 描述编排职责。"
            )
        elif pkg_id in {"dbops-engineer", "log-monitor-incident", "retention-officer"}:
            ctx["instruction"] = (
                "员工大会为汇总模式，无实时 DB/日志事件流；请基于 manifest、recent_failures 与 yuangon 节选说明职责边界与待命方式。"
            )
        elif pkg_id == "code-validator":
            ctx["instruction"] = (
                "校验 employee.yaml 时 owner/area 须为字符串；manifest.employee_config_v2 须含 actions.handlers。汇报中引用 manifest_signals 与 yuangon employee.yaml 字段，不要臆造 schema。"
            )
        elif pkg_id == "employee-pack-quality-interviewer":
            ctx["instruction"] = (
                "质询时检查 behavior_rules 是否过 long/重复、skills.brief 是否截断、employee_config_v2 结构是否完整（identity/cognition/actions/collaboration）。"
            )
        elif pkg_id in self.craft_ids:
            ctx["mode"] = "all_hands_standby"
            ctx["pipeline_area"] = "craft-workshop"
            ctx["instruction"] = (
                "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 或「输入不足」告警；说明本岗在制作车间流水线中的职责与就绪条件即可。"
            )
        return ctx
