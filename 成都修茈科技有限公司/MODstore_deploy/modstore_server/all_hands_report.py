"""数字管家「全员汇报」编排。

让在岗员工在数字管家的统一调度下，用同一个 manifest/RAG/research/metric 管线
完成三段汇报：

1. **架构 / 工作逻辑** — 从员工包 manifest（``employee_config_v2``）+ ``yuangon/``
   仓库节选反向叙述自己负责的文件结构、职责与协作依赖。
2. **遇到问题与解决方法** — 从 ``employee_execution_metrics`` 读最近失败/告警，
   写入 LLM prompt，让员工自己回顾并给出修复路径。
3. **联网 + GitHub 调研后的自我优化** — 复用 ``research_tools.build_research_context``
   抓 web + GitHub 公开材料，员工据此提出对自身文件/工作内容的优化建议，并
   声明与哪些其他岗位/manifest 字段联动。

这一管线是 :mod:`modstore_server.daily_employee_briefs` 的兄弟模块；区别：
- 调用方是数字管家而非定时邮件；
- 输出结构化 JSON（前端聊天/抽屉直接渲染）而非 HTML 邮件正文；
- 任务文案显式要求"联动其他岗位"，让汇报互相引用形成闭环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import desc

from modstore_server.daily_employee_briefs import (
    collect_yuangon_pack_excerpt,
    resolve_daily_brief_research_brief,
)
from modstore_server.duty_roster import all_planned_employee_ids, yuangon_area_for_pkg
from modstore_server.employee_executor import execute_employee_task
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    get_session_factory,
)
from modstore_server.research_tools import build_research_context
from modstore_server.services.llm import resolve_platform_bench_llm

# 单次员工大会可调度人数上限（覆盖 duty_roster 编制 52 + 余量；仍受 LLM bench 配额约束）
MAX_ALL_HANDS_EMPLOYEES = 128


def clamp_all_hands_max_employees(raw: int | float | str | None, *, default: int = 8) -> int:
    try:
        n = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, MAX_ALL_HANDS_EMPLOYEES))


logger = logging.getLogger(__name__)

AllHandsProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


# ─── 任务文案：固定结构，便于前端与 ``daily_employee_briefs`` 同步迭代 ──────────
ALL_HANDS_QA_TASK_TEMPLATE = """你是 MODstore 在岗 AI 员工 ``{employee_id}``。
现在数字管家在「员工大会」上转交一个用户提出的问题，请只用你这个岗位的视角回答。

**用户问题**（必须正面回应，不要绕开）：
> {user_question}

请基于 input 中的 ``manifest_signals`` / ``role_context`` / ``yuangon_employee_meta`` /
``yuangon_pack_excerpt`` / ``recent_failures`` /
``research_context``（如有）作答；不得编造任何不在 manifest / 节选 / 流水中的事实。

按以下固定结构输出 **简体中文 Markdown**（**不要修改二级标题措辞**）：

## 一、是否与我的岗位相关
- 在「相关 / 部分相关 / 不相关」三选一，并简述判断依据；
- 若不相关：仍要在第二节给出「我所知最相近的岗位是谁」（点 1-2 个 ``other_employees`` 中的 pkg_id）。

## 二、岗位视角下的回答
- 用 3-6 个 bullet 直接回答用户问题；
- 每条尽量绑定一项可核验的根据：``manifest_signals.handlers / depends_on / behavior_rules``、
  ``yuangon_pack_excerpt`` 中的相对路径、或 ``recent_failures`` 中的具体记录；
- 任何不能落到上述根据的推断，必须明确写「这是推断 / 待确认」。

## 三、给数字管家的协作建议（可选）
- 0-3 条；每条形如 ``owner: <pkg_id 或 self>`` + 一句话执行项；
- 优先点名 ``other_employees`` 中能补全本问题的同事（如本岗位资料不足）。

## 四、引用
- 列出本次回答用到的事实根据：每条形如 ``- <来源>: <key 或路径>``；
- 没有可引用根据时写 ``- 无可引用根据，回答仅来自 manifest 字段。``，不得空白。
"""


ALL_HANDS_TASK_TEMPLATE = """你是 MODstore 在岗 AI 员工 ``{employee_id}``。
现在数字管家正在召集"全员汇报"，请基于 input 中的 ``research_context``、
``yuangon_pack_excerpt``、``recent_failures``、``employee_label`` 与 manifest，
按下面的固定结构产出 **简体中文 Markdown**（**不要改二级标题措辞**）：

在输出前先判断输入可用性；即使有字段为空，也必须完整输出四个章节，不得拒答：
- ``yuangon_pack_excerpt`` 为空：第一节改为依据 ``manifest_signals`` + ``yuangon_area`` 写职责边界，
  并明确写出「仓库节选缺失，待同步 yuangon 目录」；不得编造相对路径；**Mermaid 架构图仍须输出**，
  仅画 manifest / ``yuangon_area`` 可支撑的最小边界，未知路径用「待同步 yuangon」类节点标注，不得臆造目录名。
- ``recent_failures`` 为空：第二节改为依据 ``manifest_signals.behavior_rules``（可辅以 persona/skills）
  写 1-3 条潜在风险与预防动作，并明确写出「近期失败流水为空」；不得编造报错记录。
- ``research_context`` 为空：第三节仍需给 2-3 条可执行建议，依据只能写 manifest 字段或
  「待联网检索验证（当前 research_context 为空）」；不得伪造网页链接或 GitHub 仓库信息。

## 一、文件与工作逻辑
- 用 **3-5 条** 描述你负责的目录/文件、对外接口、内部数据流；
- ``yuangon_pack_excerpt`` 非空时尽量引用其中相对路径；为空时引用 manifest 字段名；
- 末尾用一行总结"对外提供什么 / 依赖谁"。
- 在上述 bullet 之后，**必须**插入一段 **Mermaid** 架构图：使用 `` ```mermaid `` 代码围栏，推荐 ``flowchart LR`` 或 ``flowchart TB``，
  画出与本岗相关的目录/系统边界、数据或审核流、**CI / 审批边界**（若有：如仅提交审核状态、不直连生产库等事实）以及对外服务与上游依赖；
  图中节点与边须与上文文字及 ``yuangon_pack_excerpt`` / manifest 一致，不得臆造未出现的仓库路径或系统名；信息不足时在图注或节点标签中写「待确认 / 待同步 yuangon」。

## 二、最近遇到的问题与解决方法
- 优先解读 ``recent_failures``（``employee_execution_metrics`` 中近期失败任务）；
  若该数组为空，则结合 manifest ``behavior_rules`` / ``persona`` / ``skills`` 写"潜在风险点"；
- 每条："**问题** → **诊断** → **解决路径**"三段式，列 1-3 条。
- 不得编造未出现在 ``recent_failures`` / 节选中的故障。

## 三、上网调研后的自我优化建议
- 基于 ``research_context``（公开网页 + GitHub 仓库摘要）+ 自己的 manifest，
  提出 **2-3 条** 可立即落地的改动；
- 每条："**建议** → **依据**（节选路径 或 research_context 中的具体来源链接 / repo）
  → **联动**（点名 1-2 个其他在岗员工 ID 与他们要做的协作项）"。
- ``research_context`` 为空时，依据写 manifest 字段名或「待联网检索验证」。
- 联动至少要点到一个 ``other_employees`` 列表中的 pkg_id，方便数字管家串起来。

## 四、给数字管家的待办（可执行）
- 0-3 条机器可读的待办；每条形如：
  - ``- task: <一句话>``
  - ``  owner: <pkg_id 或 self>``
  - ``  hint: <可贴到 ai-store 搜索 / 工作流 brief 的关键词>``

禁止编造 ``research_context`` / ``yuangon_pack_excerpt`` / ``recent_failures`` 中均未出现的版本号、文件名、内部政策。
字段为空时请明确写「待确认 / 待同步」，不要输出「无法生成完整汇报」。
当 input 含 ``all_hands_standby: true`` 时：制作车间流水线岗位（intent/artifact/workflow 等）**只汇报职责与待机条件**，
不要声称已执行需要上游产物（员工包、workflow_id、产物路径）的流水线步骤；用 manifest 说明「就绪，等待上游输入」即可。
"""

# 制作车间流水线岗位：日常 cognition 会按 manifest 输出 operational JSON（含「输入不足」告警），
# 与员工大会四段 Markdown 冲突；待机汇报改走 bench 直出。

_ALL_HANDS_STANDBY_SYSTEM = """你是 MODstore 在岗 AI 员工，正在参加数字管家召集的「员工大会」。
当前为**待机汇总模式**（非制作车间流水线执行、非工作台单次任务）。

硬性要求：
- 只输出 **简体中文 Markdown**，严格按用户消息中的四段标题结构作答；**禁止**输出 JSON、禁止 ``warnings`` / ``status`` 字段。
- 缺上游产物、缺 workflow_id、缺员工包路径在待机模式下**属于正常**，不得写「输入不足」类流水线报错。
- 用 manifest / depends_on / handlers 说明本岗职责、上下游协作与「就绪，等待上游输入」即可。
- 不得编造 research_context / yuangon_pack_excerpt / recent_failures 中未出现的路径或版本号。"""


def _craft_workshop_pkg_ids() -> frozenset[str]:
    try:
        from modstore_server.duty_roster import YUANGON_AREAS

        ids = YUANGON_AREAS.get("craft-workshop", {}).get("ids") or []
        return frozenset(str(x).strip() for x in ids if str(x).strip())
    except Exception:  # noqa: BLE001
        return frozenset(
            {
                "intent-analyst",
                "employee-planner",
                "artifact-generator",
                "quality-validator",
                "miniapp-builder",
                "script-binder",
                "workflow-automator",
                "pack-registrar",
                "sandbox-tester",
                "code-validator",
                "self-checker",
                "host-checker",
                "hex-quality-assessor",
            }
        )


CRAFT_WORKSHOP_STANDBY_IDS = _craft_workshop_pkg_ids()


def _should_standby_manifest_report(pkg_id: str, *, user_question: str) -> bool:
    """制作车间 + 无用户提问 → 跳过 execute_employee_task，避免流水线 JSON 告警。"""
    return not (user_question or "").strip() and pkg_id in CRAFT_WORKSHOP_STANDBY_IDS


def _craft_pipeline_standby_context(pkg_id: str, signals: Dict[str, Any]) -> Dict[str, Any]:
    """给待机汇报补充流水线语境，避免 LLM 误判为缺上游故障。"""
    deps = signals.get("depends_on") if isinstance(signals.get("depends_on"), list) else []
    upstream = [str(d).strip() for d in deps if str(d).strip()]
    downstream_hint: Dict[str, List[str]] = {
        "intent-analyst": ["employee-planner", "artifact-generator"],
        "employee-planner": ["artifact-generator", "quality-validator"],
        "artifact-generator": ["quality-validator", "miniapp-builder"],
        "workflow-automator": ["pack-registrar"],
        "pack-registrar": ["sandbox-tester"],
        "sandbox-tester": ["code-validator", "self-checker"],
    }
    return {
        "mode": "all_hands_standby",
        "pipeline_area": "craft-workshop",
        "instruction": (
            "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 告警。"
            "说明本岗在制作车间 13 步流水线中的位置、depends_on 与就绪条件即可。"
        ),
        "upstream_employees": upstream,
        "typical_downstream": downstream_hint.get(pkg_id, []),
        "synthetic_upstream_note": (
            "当前无真实上游产物属预期；用 manifest 描述待机职责，勿写「输入不足」。"
        ),
    }


def _is_standby_pipeline_json_noise(text: str) -> bool:
    t = (text or "").strip()
    if not t.startswith("{"):
        return False
    if "输入不足" not in t and '"warnings"' not in t:
        return False
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return "输入不足" in t and "warnings" in t.lower()
    if not isinstance(obj, dict):
        return False
    warns = obj.get("warnings")
    return isinstance(warns, list) and any("输入不足" in str(w) for w in warns)


def _coerce_standby_excerpt(text: str, row: Dict[str, Any]) -> str:
    """把待机误输出的流水线 JSON 告警压成可读一句，避免污染会议摘要。"""
    if not _is_standby_pipeline_json_noise(text):
        return text
    eid = str(row.get("employee_id") or "").strip()
    name = str(row.get("name") or eid).strip()
    area = str(row.get("area") or "制作车间").strip() or "制作车间"
    summ = ""
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            summ = str(obj.get("summary") or "").strip()
    except json.JSONDecodeError:
        pass
    if summ and not summ.startswith("{") and "输入不足" not in summ[:80]:
        return summ
    return (
        f"【{name}】（{eid}）在 {area} 流水线中处于**待机**："
        f"职责与 manifest 已就绪，等待上游工单/产物输入；本次大会未执行流水线步骤，无异常。"
    )


# ─── 数据加载 ─────────────────────────────────────────────────────────────────


def _resolve_employee_pairs(
    requested_ids: Optional[List[str]],
    *,
    max_employees: int,
) -> List[Tuple[str, str]]:
    """返回 ``[(pkg_id, display_name), ...]``。

    **编制员工**（``duty_roster.all_planned_employee_ids``）与公开市场无关：不要求
    ``catalog_items.is_public``，也不要求已做「市场上架」。只要能加载员工包即可：

    - Postgres ``catalog_items`` 中 ``artifact=employee_pack``；**或**
    - XC 本地 ``catalog_store.packages.json`` 中已登记 ``artifact=employee_pack`` 且
      ``files/`` 下有对应 zip（与 :func:`modstore_server.employee_runtime.load_employee_pack` 一致）。
    """
    roster = all_planned_employee_ids()
    from modstore_server.catalog_store import employee_pack_records_from_store

    xc = employee_pack_records_from_store()
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(CatalogItem.pkg_id, CatalogItem.name)
            .filter(CatalogItem.artifact == "employee_pack")
            .all()
        )
    db_ids = {str(r[0]) for r in rows}
    name_by_id = {str(r[0]): str(r[1] or r[0]) for r in rows}
    for pid, rec in xc.items():
        if pid not in name_by_id:
            name_by_id[pid] = str(rec.get("name") or pid).strip() or pid

    xc_ids = set(xc.keys())
    available = db_ids | xc_ids

    if requested_ids:
        pairs: List[Tuple[str, str]] = []
        for pid in requested_ids:
            pid = str(pid or "").strip()
            if not pid or pid not in available:
                continue
            pairs.append((pid, name_by_id.get(pid, pid)))
    else:
        pairs = sorted(
            ((pid, name_by_id.get(pid, pid)) for pid in roster if pid in available),
            key=lambda x: x[0],
        )
    return pairs[: clamp_all_hands_max_employees(max_employees)]


def _recent_failures(employee_id: str, limit: int = 6) -> List[Dict[str, Any]]:
    """读员工最近真实失败/告警的执行流水，给"问题与解决"段落做事实根基。

    只纳入真正的失败状态（``failed``、``error``，以及有非空 error 字段的 ``success``）；
    排除 ``skipped``、``blocked_by_risk_gate``、``warning`` 等正常/预期状态。
    默认只取最近 72h 内的记录（可通过 ``MODSTORE_RECENT_FAILURES_HOURS`` 覆盖）。
    同一 ``(task 前缀, error 前缀)`` 组合去重，避免重复 craft 步骤生成多张 P0 卡。
    """
    import os

    hours = int(os.environ.get("MODSTORE_RECENT_FAILURES_HOURS") or 72)
    sf = get_session_factory()
    out: List[Dict[str, Any]] = []
    seen_keys: set = set()
    with sf() as session:
        cutoff: Optional[datetime] = None
        if hours > 0:
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)

        q = session.query(EmployeeExecutionMetric).filter(
            EmployeeExecutionMetric.employee_id == employee_id
        )
        if cutoff is not None:
            q = q.filter(EmployeeExecutionMetric.created_at >= cutoff)
        rows = q.order_by(desc(EmployeeExecutionMetric.id)).limit(120).all()

        for r in rows:
            status = str(getattr(r, "status", "") or "")
            err = (getattr(r, "error", "") or "").strip()

            # 只纳入真实失败；skipped / blocked_by_risk_gate / warning 等均排除
            is_real_failure = status in ("failed", "error")
            is_success_with_err = status == "success" and bool(err)
            if not (is_real_failure or is_success_with_err):
                continue

            # 按 (task 前60字, error 前80字) 去重，同类 craft 步骤只保留最新一条
            task_key = str(r.task or "")[:60]
            err_key = err[:80]
            dedup = (task_key, err_key)
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)

            out.append(
                {
                    "id": int(r.id),
                    "task": str(r.task or "")[:160],
                    "status": status,
                    "duration_ms": float(r.duration_ms or 0.0),
                    "llm_tokens": int(r.llm_tokens or 0),
                    "error": err[:600],
                    "created_at": (
                        r.created_at.replace(tzinfo=timezone.utc).isoformat()
                        if isinstance(r.created_at, datetime) and r.created_at.tzinfo is None
                        else (r.created_at.isoformat() if r.created_at else None)
                    ),
                }
            )
            if len(out) >= limit:
                break
    return out


def _load_yuangon_employee_meta(pkg_id: str) -> Dict[str, Any]:
    """读取 yuangon/<area>/<pkg_id>/employee.yaml 中的 owner/area/domain 等元数据。"""
    from modstore_server.daily_employee_briefs import _resolve_pack_dir

    area = yuangon_area_for_pkg(pkg_id) or ""
    if not area:
        return {}
    _root, pack_dir = _resolve_pack_dir(area, pkg_id)
    yaml_path = pack_dir / "employee.yaml"
    if not yaml_path.is_file():
        return {"area": area}
    try:
        import yaml

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("all_hands: employee.yaml read failed pkg_id=%s err=%s", pkg_id, exc)
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
        meta["ci_coverage_artifacts"] = [str(x).strip() for x in ci_paths if str(x).strip()][:12]
    return meta


def _snapshot_pending_change_requests(limit: int = 12) -> List[Dict[str, Any]]:
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    out: List[Dict[str, Any]] = []
    try:
        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "pending")
                .order_by(desc(EmployeeChangeRequest.id))
                .limit(max(1, min(limit, 30)))
                .all()
            )
            for r in rows:
                out.append(
                    {
                        "id": int(r.id),
                        "source_employee_id": str(r.source_employee_id or ""),
                        "change_kind": str(r.change_kind or ""),
                        "risk_level": str(r.risk_level or ""),
                        "status": str(r.status or ""),
                        "diff_summary": str(r.diff_summary or "")[:400],
                        "target_paths": (
                            json.loads(r.target_paths_json or "[]")[:6]
                            if str(r.target_paths_json or "").strip().startswith("[")
                            else []
                        ),
                        "git_branch": str(r.git_branch or "")[:120],
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("all_hands: pending change requests snapshot failed: %s", exc)
    return out


def _snapshot_employee_cron_overview(limit: int = 24) -> List[Dict[str, Any]]:
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        jobs = list_employee_cron_jobs() or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("all_hands: cron overview failed: %s", exc)
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


def _all_hands_role_context(pkg_id: str) -> Dict[str, Any]:
    """按岗位注入员工大会专用上下文，避免「缺 Change ID / 缺调度清单」类空答。"""
    ctx: Dict[str, Any] = {"mode": "all_hands_meeting"}
    if pkg_id == "change-request-auditor":
        pending = _snapshot_pending_change_requests()
        ctx["pending_change_requests"] = pending
        ctx["instruction"] = (
            "若 pending_change_requests 非空：逐条引用 id / source_employee_id / diff_summary 说明评审要点；"
            "若为空：说明当前无待审变更，并列出 manifest 中的评审流程与 depends_on。"
        )
    elif pkg_id == "daily-orchestrator":
        ctx["employee_cron_overview"] = _snapshot_employee_cron_overview()
        ctx["instruction"] = (
            "结合 employee_cron_overview 说明当前定时任务覆盖与缺口；无记录时依据 manifest 描述编排职责。"
        )
    elif pkg_id in {"dbops-engineer", "log-monitor-incident", "retention-officer"}:
        ctx["instruction"] = (
            "员工大会为汇总模式，无实时 DB/日志事件流；请基于 manifest、recent_failures 与 yuangon 节选说明职责边界与待命方式。"
        )
    elif pkg_id == "code-validator":
        ctx["instruction"] = (
            "校验 employee.yaml 时 owner/area 须为字符串；manifest.employee_config_v2 须含 actions.handlers。"
            "汇报中引用 manifest_signals 与 yuangon employee.yaml 字段，不要臆造 schema。"
        )
    elif pkg_id == "employee-pack-quality-interviewer":
        ctx["instruction"] = (
            "质询时检查 behavior_rules 是否过 long/重复、skills.brief 是否截断、"
            "employee_config_v2 结构是否完整（identity/cognition/actions/collaboration）。"
        )
    elif pkg_id in CRAFT_WORKSHOP_STANDBY_IDS:
        ctx["mode"] = "all_hands_standby"
        ctx["pipeline_area"] = "craft-workshop"
        ctx["instruction"] = (
            "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 或「输入不足」告警；"
            "说明本岗在制作车间流水线中的职责与就绪条件即可。"
        )
    return ctx


def _manifest_signals(pkg_id: str) -> Dict[str, Any]:
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
    yuangon_meta = _load_yuangon_employee_meta(pkg_id)
    out["owner"] = str(yuangon_meta.get("owner") or "")
    out["area"] = str(yuangon_meta.get("area") or yuangon_area_for_pkg(pkg_id) or "")
    out["domain"] = str(yuangon_meta.get("domain") or "")
    try:
        sf = get_session_factory()
        with sf() as session:
            pack = load_employee_pack(session, pkg_id)
        man = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        v2 = man.get("employee_config_v2") if isinstance(man, dict) else {}
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
        if sp and not out["persona"]:
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
        wp = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
        scope_globs = wp.get("scope_globs") if isinstance(wp.get("scope_globs"), list) else []
        forbidden_globs = (
            wp.get("forbidden_globs") if isinstance(wp.get("forbidden_globs"), list) else []
        )
        ident_block = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
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
            "workspace_forbidden_globs": [str(x) for x in forbidden_globs if str(x).strip()][:4],
            "skills_count": len(out["skills"]),
            "behavior_rules_count": len(out["behavior_rules"]),
        }
        try:
            out["workflow_id"] = int(wf.get("workflow_id") or 0)
        except (TypeError, ValueError):
            out["workflow_id"] = 0
        sig_block = (
            v2.get("manifest_signals") if isinstance(v2.get("manifest_signals"), dict) else {}
        )
        ci_art = sig_block.get("ci_coverage_artifacts")
        if isinstance(ci_art, list) and ci_art:
            out["ci_coverage_artifacts"] = [str(x).strip() for x in ci_art if str(x).strip()][:12]
    except Exception as exc:  # noqa: BLE001
        logger.debug("all_hands: manifest read failed pkg_id=%s err=%s", pkg_id, exc)
    if "ci_coverage_artifacts" not in out:
        yg_ci = yuangon_meta.get("ci_coverage_artifacts")
        if isinstance(yg_ci, list) and yg_ci:
            out["ci_coverage_artifacts"] = [str(x).strip() for x in yg_ci if str(x).strip()][:12]
    bc = yuangon_meta.get("business_context")
    if isinstance(bc, dict) and bc:
        out["business_context"] = bc
    return out


# ─── 单个员工汇报 ─────────────────────────────────────────────────────────────


async def _standby_manifest_report_via_bench(
    *,
    pkg_id: str,
    display_name: str,
    task_text: str,
    inp: Dict[str, Any],
    user_id: int,
    bench_provider: str,
    bench_model: str,
) -> Tuple[str, str, int]:
    """制作车间待机：用大会任务模板 + bench LLM，不经员工 cognition（避免 JSON 告警）。"""
    payload = dict(inp)
    if pkg_id in CRAFT_WORKSHOP_STANDBY_IDS:
        sig = payload.get("manifest_signals")
        if isinstance(sig, dict):
            payload["craft_workshop_standby"] = _craft_pipeline_standby_context(pkg_id, sig)

    user_content = (
        f"{task_text}\n\n---\n\n"
        f"以下为结构化输入（JSON），请据此撰写四段 Markdown 汇报：\n"
        f"{json.dumps(payload, ensure_ascii=False)[:14000]}"
    )
    messages = [
        {"role": "system", "content": _ALL_HANDS_STANDBY_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db,
                int(user_id or 0),
                bench_provider,
                bench_model,
                messages,
                max_tokens=4096,
            )
    except Exception as exc:  # noqa: BLE001
        return "", f"待机汇报 LLM 异常：{exc}"[:800], 0

    if not isinstance(result, dict) or not result.get("ok"):
        err = str((result or {}).get("error") or "bench LLM 未返回有效内容").strip()
        return "", err[:800], 0

    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg0 = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg0, dict):
                md = str(msg0.get("content") or "").strip()
    tokens = 0
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    usage = raw.get("usage") if isinstance(raw, dict) else {}
    if isinstance(usage, dict):
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    return md, "", tokens


async def _report_one_employee(
    *,
    pkg_id: str,
    display_name: str,
    other_employees: List[str],
    user_id: int,
    bench_provider: str,
    bench_model: str,
    with_research: bool,
    user_question: Optional[str] = None,
) -> Dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    warns: List[str] = []

    research_pack = ""
    research_sources: List[Dict[str, str]] = []
    if with_research:
        seed = resolve_daily_brief_research_brief(pkg_id, display_name)
        try:
            rc = await build_research_context(
                brief=seed,
                intent="employee",
                max_repos=2,
                max_chars=5000,
                max_web=6,
                user_id=user_id,
                rate_limit_bucket="agent_tool",
            )
            if rc.get("ok"):
                research_pack = str(rc.get("context_pack") or "")
                research_sources = [
                    {
                        "title": str(s.get("title") or ""),
                        "url": str(s.get("url") or ""),
                    }
                    for s in (rc.get("sources") or [])
                    if isinstance(s, dict)
                ][:8]
            else:
                warns.append(str(rc.get("error") or "research failed"))
            for w in rc.get("warnings") or []:
                warns.append(str(w))
        except Exception as exc:  # noqa: BLE001
            logger.warning("all_hands research failed pkg_id=%s err=%s", pkg_id, exc)
            warns.append(f"research 失败：{exc}")

    excerpt, yg_warns = collect_yuangon_pack_excerpt(pkg_id)
    warns.extend(yg_warns)

    failures = _recent_failures(pkg_id)
    yuangon_meta = _load_yuangon_employee_meta(pkg_id)
    signals = _manifest_signals(pkg_id)

    user_q = (user_question or "").strip()
    if user_q:
        task_text = ALL_HANDS_QA_TASK_TEMPLATE.format(
            employee_id=pkg_id,
            user_question=user_q,
        )
    else:
        task_text = ALL_HANDS_TASK_TEMPLATE.format(employee_id=pkg_id)
    inp: Dict[str, Any] = {
        "research_context": research_pack,
        "research_sources": research_sources,
        "yuangon_pack_excerpt": excerpt,
        "recent_failures": failures,
        "context_availability": {
            "yuangon_excerpt": bool(excerpt.strip()),
            "research_pack": bool(research_pack.strip()),
            "execution_failures": bool(failures),
        },
        "employee_id": pkg_id,
        "employee_label": display_name,
        "manifest_signals": signals,
        "other_employees": other_employees,
        "yuangon_area": yuangon_area_for_pkg(pkg_id) or "",
        "yuangon_employee_meta": yuangon_meta,
        "role_context": _all_hands_role_context(pkg_id),
        "user_question": user_q,
        "all_hands_standby": not bool(user_q),
        # 管家编排的全员汇报在服务端执行；含 shell_exec 等 handler 的岗位否则会被
        # employee_risk_middleware 判为 high 并在入口拦截（无 Markdown、metrics 记 blocked_by_risk_gate）。
        "allow_high_risk_real_run": True,
    }
    _hr_gate = (os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()
    if _hr_gate:
        inp["high_risk_gate_token"] = _hr_gate

    use_standby_bench = _should_standby_manifest_report(pkg_id, user_question=user_q)
    llm_tokens = 0
    duration_ms = 0.0

    if use_standby_bench:
        text, cog_err, llm_tokens = await _standby_manifest_report_via_bench(
            pkg_id=pkg_id,
            display_name=display_name,
            task_text=task_text,
            inp=inp,
            user_id=user_id,
            bench_provider=bench_provider,
            bench_model=bench_model,
        )
        if text:
            text = _coerce_standby_excerpt(
                text, {"employee_id": pkg_id, "name": display_name, "area": signals.get("area")}
            )
        completed = datetime.now(timezone.utc).isoformat()
        return {
            "employee_id": pkg_id,
            "name": display_name,
            "area": yuangon_area_for_pkg(pkg_id) or "",
            "status": "ok" if text else ("model_error" if cog_err else "empty"),
            "started_at": started_at,
            "completed_at": completed,
            "report_markdown": text,
            "cognition_error": cog_err[:800],
            "warnings": warns,
            "manifest_signals": signals,
            "recent_failures": failures,
            "research_sources": research_sources,
            "duration_ms": duration_ms,
            "llm_tokens": llm_tokens,
            "report_mode": "standby_manifest_bench",
        }

    def _run() -> Dict[str, Any]:
        return execute_employee_task(
            pkg_id,
            task_text,
            inp,
            user_id,
            bench_llm_override=(bench_provider, bench_model),
        )

    out: Dict[str, Any] = {}
    try:
        from modstore_server.employee_executor import _is_transient_llm_error  # noqa: PLC0415

        for attempt in range(3):
            out = await asyncio.to_thread(_run)
            cog_err = str(out.get("cognition_error") or "").strip()
            cog_err_lower = cog_err.lower()
            if (
                attempt < 2
                and cog_err
                and (
                    "429" in cog_err_lower
                    or "rate limit" in cog_err_lower
                    or "too many requests" in cog_err_lower
                    or _is_transient_llm_error(cog_err)
                )
            ):
                await asyncio.sleep(2.5 * (attempt + 1))
                continue
            break
    except Exception as exc:  # noqa: BLE001
        logger.exception("all_hands employee execute failed pkg_id=%s", pkg_id)
        return {
            "employee_id": pkg_id,
            "name": display_name,
            "area": yuangon_area_for_pkg(pkg_id) or "",
            "status": "error",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "report_markdown": "",
            "cognition_error": str(exc)[:800],
            "warnings": warns + [f"执行抛异常：{exc}"[:200]],
            "manifest_signals": signals,
            "recent_failures": failures,
            "research_sources": research_sources,
        }

    text = (out.get("reasoning_excerpt") or "").strip()
    if inp.get("all_hands_standby"):
        text = _coerce_standby_excerpt(
            text,
            {
                "employee_id": pkg_id,
                "name": display_name,
                "area": yuangon_area_for_pkg(pkg_id) or "",
            },
        )
    cog_err = (out.get("cognition_error") or "").strip()
    return {
        "employee_id": pkg_id,
        "name": display_name,
        "area": yuangon_area_for_pkg(pkg_id) or "",
        "status": "ok" if text else ("model_error" if cog_err else "empty"),
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "report_markdown": text,
        "cognition_error": cog_err[:800],
        "warnings": warns,
        "manifest_signals": signals,
        "recent_failures": failures,
        "research_sources": research_sources,
        "duration_ms": float(out.get("duration_ms") or 0.0),
        "llm_tokens": int(out.get("llm_tokens") or 0),
    }


# ─── 综合答复（数字管家把 19 名员工的回答合并） ──────────────────────────────


_SYNTHESIZE_SYSTEM_PROMPT = """你是 MODstore 的「数字管家」。
管理员把同一个问题转发给在岗的多名员工，并把每位员工以自己岗位视角写的答复
作为输入交给你。你需要：

1) 用一句话给出最终答复（是 / 否 / 部分 / 暂不确定）；
2) 用 3-6 个 bullet 综合所有员工的事实（必须**点名引用** ``employee_id``）；
3) 如果不同员工存在分歧，单独写一节「分歧」并标出谁说什么；
4) 给出 0-3 条对管理员的下一步建议（每条 ``owner: <pkg_id 或 self>`` 形式）。

硬性要求：
- 仅基于输入的员工答复内容，不得编造任何员工没说过的事实。
- 引用员工时使用 ``[pkg_id]`` 这种方括号形式，便于前端转链接。
- 整体输出 **简体中文 Markdown**。
"""


def _employee_answer_excerpt(row: Dict[str, Any], *, max_chars: int = 800) -> str:
    md = str(row.get("report_markdown") or "").strip()
    if md:
        if row.get("report_mode") == "standby_manifest_bench" or _is_standby_pipeline_json_noise(
            md
        ):
            md = _coerce_standby_excerpt(md, row)
        return md[:max_chars]
    err = str(row.get("cognition_error") or "").strip()
    if err:
        return f"（员工执行失败：{err}）"
    warns = row.get("warnings") or []
    if isinstance(warns, list) and warns:
        filtered = [
            str(w)
            for w in warns
            if str(w).strip()
            and "输入不足" not in str(w)
            and "research failed" not in str(w).lower()
        ]
        if filtered:
            return f"（员工无报告，警告：{'; '.join(filtered)[:max_chars]}）"
    return "（员工无报告）"


async def synthesize_all_hands_answer(
    *,
    user_question: str,
    employees: List[Dict[str, Any]],
    bench_provider: str,
    bench_model: str,
    user_id: int,
) -> Dict[str, Any]:
    """把多名员工的 Q&A 答复送给 bench LLM 合并成「数字管家综合答复」。

    返回 ``{ markdown, cited_employees: [pkg_id], model, error }``；
    bench LLM 不可用或失败时 ``markdown == ""`` 且 ``error`` 非空。
    """
    started_at = datetime.now(timezone.utc).isoformat()
    cited = [
        str(r.get("employee_id") or "").strip()
        for r in employees
        if str(r.get("employee_id") or "").strip()
    ]
    if not bench_provider or not bench_model:
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": "",
            "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
        }

    parts: List[str] = []
    for row in employees:
        eid = str(row.get("employee_id") or "").strip()
        name = str(row.get("name") or eid).strip()
        area = str(row.get("area") or "").strip()
        if not eid:
            continue
        excerpt = _employee_answer_excerpt(row)
        parts.append(f"### [{eid}] {name}（区域：{area or '未知'}）\n\n{excerpt}")

    body = "\n\n".join(parts) if parts else "（没有可合并的员工答复）"
    user_content = (
        f"管理员问题：\n{(user_question or '').strip()}\n\n"
        f"以下是 {len(parts)} 名员工以自身岗位视角给出的答复：\n\n{body}"
    )
    messages = [
        {"role": "system", "content": _SYNTHESIZE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db,
                int(user_id or 0),
                bench_provider,
                bench_model,
                messages,
                max_tokens=2048,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("synthesize_all_hands_answer dispatch failed")
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": f"调用 bench LLM 异常：{exc}",
        }

    if not isinstance(result, dict) or not result.get("ok"):
        err = ""
        if isinstance(result, dict):
            err = str(result.get("error") or "").strip()
        return {
            "question": user_question,
            "markdown": "",
            "cited_employees": cited,
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": err or "bench LLM 未返回有效内容",
        }

    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                md = str(msg.get("content") or "").strip()
    return {
        "question": user_question,
        "markdown": md,
        "cited_employees": cited,
        "generated_at": started_at,
        "model": f"{bench_provider}/{bench_model}",
        "error": "" if md else "bench LLM 返回为空",
    }


_MEETING_MINUTES_SYSTEM_PROMPT = """你是 MODstore 的数字管家秘书，根据「员工大会」上各 AI 员工的汇报节选（及可能有的综合答复），写一份给**管理员**看的会议摘要。

写作风格（说人话）：
- 用**大白话、短句**，像跟同事口头汇报；避免堆砌英文缩写、handler 名、JSON 字段名。
- 技术细节只保留管理员能决策的信息（谁负责、卡在哪、下一步做什么）。
- 制作车间岗位在**待机汇总**时写「流水线就绪、等待工单」即可；不要把「缺上游输入」当成故障反复写。

硬性要求：
- **仅基于**输入中出现的汇报与综合答复归纳；不得编造输入中不存在的事实。
- 忽略节选里残留的 operational JSON、「输入不足」类流水线告警（待机模式下属正常）。
- 输出用 **简体中文**，且**严格按下面结构**（第一行必须是「会议摘要」四字，随后「一、」到「五、」标题措辞不可改）：

会议摘要
一、会议主题：……
二、现状（各岗在做什么 / 待机情况）：……
三、问题与风险
- ……
四、下一步
- ……
五、其他说明：……

- 「三」「四」下用 Markdown 无序列表，以 `- ` 开头；若无问题或可写「- 无」。
- 「五」可写「无」或一句补充。
- 不要添加与上述结构无关的前言、后记或思维链。"""


async def synthesize_meeting_minutes(
    *,
    report: Dict[str, Any],
    user_id: int,
) -> Dict[str, Any]:
    """将已成功生成的 ``build_all_hands_report`` 结果压缩为五段式「会议摘要」正文。

    返回 ``{ text, generated_at, model, error }``；失败时 ``text`` 可为空且 ``error`` 非空。
    """
    started_at = datetime.now(timezone.utc).isoformat()
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    bench_provider = str(summary.get("bench_provider") or "").strip()
    bench_model = str(summary.get("bench_model") or "").strip()
    if not bench_provider or not bench_model:
        return {
            "text": "",
            "generated_at": started_at,
            "model": "",
            "error": "平台 Bench LLM 未配置（报告 summary 中无 bench）",
        }

    raw_emp = report.get("employees") or []
    employees: List[Dict[str, Any]] = raw_emp if isinstance(raw_emp, list) else []
    parts: List[str] = []
    for row in employees:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("employee_id") or "").strip()
        name = str(row.get("name") or eid).strip()
        if not eid:
            continue
        excerpt = _employee_answer_excerpt(row, max_chars=1200)
        st = str(row.get("status") or "").strip()
        parts.append(f"### [{eid}] {name}（状态：{st}）\n\n{excerpt}")
    body_emp = "\n\n".join(parts) if parts else "（无员工汇报）"

    uq = str(summary.get("user_question") or "").strip()
    synth_extra = ""
    synth = report.get("synthesized_answer")
    if isinstance(synth, dict):
        sm = str(synth.get("markdown") or "").strip()
        if sm:
            synth_extra = f"\n\n## 数字管家综合答复（员工大会问答）\n\n{sm[:4000]}"

    standby_note = ""
    if not uq:
        craft_n = sum(
            1
            for row in employees
            if isinstance(row, dict)
            and str(row.get("employee_id") or "") in CRAFT_WORKSHOP_STANDBY_IDS
        )
        if craft_n:
            standby_note = (
                f"\n\n> 说明：本次为**待机汇总**（无管理员提问），制作车间约 {craft_n} 个岗位"
                "为流水线就绪汇报；节选中的「缺上游」勿当作故障。\n"
            )

    user_content = (
        "以下是一次员工大会收集到的各岗汇报节选，请据此撰写会议摘要（说人话、给管理员看）。\n\n"
        + (f"管理员提问：{uq}\n\n" if uq else "")
        + standby_note
        + f"## 各员工汇报节选\n\n{body_emp}{synth_extra}"
    )
    messages = [
        {"role": "system", "content": _MEETING_MINUTES_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db,
                int(user_id or 0),
                bench_provider,
                bench_model,
                messages,
                max_tokens=2048,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("synthesize_meeting_minutes dispatch failed")
        return {
            "text": "",
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": f"调用 bench LLM 异常：{exc}",
        }

    if not isinstance(result, dict) or not result.get("ok"):
        err = ""
        if isinstance(result, dict):
            err = str(result.get("error") or "").strip()
        return {
            "text": "",
            "generated_at": started_at,
            "model": f"{bench_provider}/{bench_model}",
            "error": err or "bench LLM 未返回有效内容",
        }

    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg0 = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg0, dict):
                md = str(msg0.get("content") or "").strip()
    return {
        "text": md,
        "generated_at": started_at,
        "model": f"{bench_provider}/{bench_model}",
        "error": "" if md else "bench LLM 返回为空",
    }


# ─── 全员入口 ─────────────────────────────────────────────────────────────────


async def build_all_hands_report(
    *,
    employee_ids: Optional[List[str]] = None,
    max_employees: int = 8,
    with_research: bool = True,
    user_id: int = 0,
    concurrency: int = 2,
    progress_cb: Optional[AllHandsProgressCallback] = None,
    user_question: Optional[str] = None,
    synthesize: bool = False,
) -> Dict[str, Any]:
    """全员汇报主入口。返回结构化 JSON，前端直接渲染。

    - ``employee_ids`` 为空时：取 ``duty_roster`` ∩ ``catalog`` 全集，按 ``pkg_id`` 排序；
    - ``concurrency`` 默认 2，避免一次性把平台 LLM Bench 配额打满；
    - 不抛异常：单个员工失败时 ``status='error'``，整体仍返回。
    """

    async def _emit_progress(payload: Dict[str, Any]) -> None:
        if not progress_cb:
            return
        try:
            await progress_cb(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("all_hands progress callback failed: %s", exc)

    started_at = datetime.now(timezone.utc).isoformat()
    pairs = _resolve_employee_pairs(employee_ids, max_employees=max_employees)
    await _emit_progress(
        {
            "stage": "prepare",
            "total": len(pairs),
            "completed": 0,
            "ok": 0,
            "error": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if not pairs:
        return {
            "ok": False,
            "error": "无可汇报员工：duty_roster 与 catalog 交集为空",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "employees": [],
            "summary": {},
        }

    bench_prov, bench_mdl = resolve_platform_bench_llm()
    if not bench_prov or not bench_mdl:
        return {
            "ok": False,
            "error": "平台 Bench LLM 未配置（MODSTORE_EMPLOYEE_BENCH_* 或平台 Key）",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "employees": [],
            "summary": {},
        }

    other_ids = [pid for pid, _ in pairs]
    sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
    stagger_sec = float(os.environ.get("MODSTORE_ALL_HANDS_STAGGER_SEC", "1.0") or "1.0")
    stagger_lock = asyncio.Lock()
    stagger_seq = 0

    done_lock = asyncio.Lock()
    done_count = 0
    done_ok = 0
    done_error = 0

    async def _wrapped(pid: str, name: str) -> Dict[str, Any]:
        nonlocal done_count, done_ok, done_error, stagger_seq
        async with sem:
            if stagger_sec > 0 and len(pairs) > 4:
                async with stagger_lock:
                    idx = stagger_seq
                    stagger_seq += 1
                await asyncio.sleep(min(idx * stagger_sec * 0.25, 6.0))
            row = await _report_one_employee(
                pkg_id=pid,
                display_name=name,
                other_employees=[x for x in other_ids if x != pid],
                user_id=user_id,
                bench_provider=bench_prov,
                bench_model=bench_mdl,
                with_research=with_research,
                user_question=user_question,
            )
        status = str(row.get("status") or "")
        async with done_lock:
            done_count += 1
            if status == "ok":
                done_ok += 1
            elif status in {"error", "model_error"}:
                done_error += 1
            snap_done = done_count
            snap_ok = done_ok
            snap_error = done_error
        await _emit_progress(
            {
                "stage": "employee_done",
                "employee_id": pid,
                "employee_name": name,
                "employee_status": status,
                "total": len(pairs),
                "completed": snap_done,
                "ok": snap_ok,
                "error": snap_error,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return row

    employees = await asyncio.gather(*[_wrapped(p, n) for p, n in pairs])

    ok_count = sum(1 for e in employees if e.get("status") == "ok")
    error_count = sum(1 for e in employees if e.get("status") in {"error", "model_error"})
    summary = {
        "total": len(employees),
        "ok": ok_count,
        "error": error_count,
        "with_research": bool(with_research),
        "bench_provider": bench_prov,
        "bench_model": bench_mdl,
        "user_question": (user_question or "").strip(),
        "synthesized": False,
    }
    await _emit_progress(
        {
            "stage": "completed",
            "total": len(employees),
            "completed": len(employees),
            "ok": ok_count,
            "error": error_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    synthesized_answer: Optional[Dict[str, Any]] = None
    if synthesize and (user_question or "").strip():
        await _emit_progress(
            {
                "stage": "synthesize",
                "total": len(employees),
                "completed": len(employees),
                "ok": ok_count,
                "error": error_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        synthesized_answer = await synthesize_all_hands_answer(
            user_question=user_question or "",
            employees=employees,
            bench_provider=bench_prov,
            bench_model=bench_mdl,
            user_id=user_id,
        )
        summary["synthesized"] = bool(
            synthesized_answer
            and (synthesized_answer.get("markdown") or "").strip()
            and not (synthesized_answer.get("error") or "").strip()
        )

    return {
        "ok": True,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "employees": employees,
        "summary": summary,
        "synthesized_answer": synthesized_answer,
    }


def all_hands_concurrency_default() -> int:
    """允许通过环境变量覆盖的默认并发上限。"""
    raw = (os.environ.get("MODSTORE_ALL_HANDS_CONCURRENCY") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 4))
    return 2
