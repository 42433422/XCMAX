# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
"""每日摘要邮件：catalog 与编制交集内的员工岗位简报（联网调研 + LLM）。

可见「文件」与索引的两条路径（排查员工看不见资料时）：

1. **知识库 RAG**（员工 cognition.knowledge）：文档须入库并完成向量化；集合须对当前上下文可见
   （员工自有、grant、public）。定时简报默认 ``user_id=0``，用户名下私有集合不可见；若要把某登录用户的
   知识库纳入简报检索，设置环境变量 ``MODSTORE_DAILY_BRIEF_USER_ID`` 为该用户数字 ID。
2. **Agent 读仓库**：与工作台/API 手动执行相同，须在 ``input_data`` 中提供合法 ``project_root``；
   简报任务本身不传 ``project_root``，不走仅依赖本地树的 Agent 读文件路径。
3. **编制目录节选**（与 Glob 类工具目的相同、适合定时任务）：当设置 ``MODSTORE_REPO_ROOT`` 且
   ``MODSTORE_DAILY_BRIEF_GROUND_YUANGON=1``（默认）时，在调用 LLM 前从
   ``yuangon/<area>/<pkg_id>/`` 预读若干文件（含 ``prompts/*.md``、``tasks/*.json``、可选 env / manifest glob）的截断文本，
   注入 ``yuangon_pack_excerpt``，使邮件中的建议能引用仓库内真实职责与范围。

可选 ``MODSTORE_DAILY_BRIEF_STRICT_GROUNDING``、``MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON`` 与 manifest ``daily_brief_ground_paths`` 见模块内函数说明与环境变量文档。

详见 ``rag_service.visible_collection_ids``、``employee_executor._cognition_real`` / ``_action_agent_runner``。
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Dict, List, Tuple

from modstore_server.daily_brief_grounding import _resolve_pack_dir as _resolve_pack_dir
from modstore_server.daily_brief_grounding import (
    collect_yuangon_pack_excerpt as collect_yuangon_pack_excerpt,
)
from modstore_server.duty_roster import all_planned_employee_ids
from modstore_server.employee_executor import execute_employee_task
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.models import CatalogItem, get_session_factory
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from modstore_server.research_tools import build_research_context
from modstore_server.services.llm import resolve_platform_bench_llm

logger = logging.getLogger(__name__)

_TRUST_HINT = (
    "信任层级：yuangon_pack_excerpt 与知识库 RAG（若有）代表**本仓库/已入库**材料，优先采信；"
    "research_context 来自**公开互联网等第三方检索**，仅供参考，**不得当作公司已发布的内规**。"
    "若二者冲突，以 yuangon 节选为准；不确定请写「待确认」。"
)

DAILY_BRIEF_TASK = f"""你是 MODstore 在岗 AI 员工。请阅读 input 中的 research_context、yuangon_pack_excerpt 及整条 JSON。
{_TRUST_HINT}
yuangon_pack_excerpt 若为非空，即本仓库该岗位在 yuangon/ 下的真实文件节选，请**优先依据其中职责、范围、技能名** 叙述，勿编造节选中不存在的具体版本号。
输出 **简体中文 Markdown**，固定结构（不要改二级标题措辞）：
## 工作内容摘要
（3～6 句：用管理者读得懂的话，概括本岗**当前职责、节选中的事实要点**；若有 research_context，可补充 1～2 句相关公开动态；避免空话与堆砌术语）
## 新方案与下一步
（基于上一节「工作内容摘要」，提出 **2～4 条** 可落地的改进或新方案；编号列表；每条一行写清「做什么、为何与当前工作相关」）
（优先对齐 yuangon 节选；节选不足时可引用 research_context；勿编造两边都没有的细节）
## 待办任务
（**2～5 条** 近期可执行事项：**编号列表**；每条写清动作、对象或路径；若可知负责人或截止日期请括注；否则写「待指派」或「待确认」）
## 风险或依赖（可选）
（0～3 句：仅在有实质依赖时填写）
禁止编造 research_context / yuangon_pack_excerpt 中均未出现的具体版本号或文件名；不确定请写「待确认」。"""

DAILY_BRIEF_TASK_STRICT = f"""你是 MODstore 在岗 AI 员工。请阅读 input 中的 research_context、yuangon_pack_excerpt 及整条 JSON。
{_TRUST_HINT}
若 yuangon_pack_excerpt **为空**：禁止编造本岗位仓库内规或具体文件名；「工作内容摘要」须明确说明仓库节选缺失，可写运维侧通用提醒或「待同步 yuangon 目录」。
若 yuangon_pack_excerpt **非空**：「新方案与下一步」每条须能在节选或 research_context 中找到依据。
输出 **简体中文 Markdown**，固定结构（不要改二级标题措辞）：
## 工作内容摘要
（3～6 句，同上）
## 新方案与下一步
1. 建议正文……
   **依据**：`相对路径` — 摘录原文不超过约 80 字（须来自 yuangon_pack_excerpt）
2. ……
   **依据**：外部检索 — 简述与 research_context 中哪一句对应（仅当本建议无法从节选支撑时）
3. ……
   **依据**：……
（至少 2 条、至多 4 条）
## 待办任务
（**2～5 条**：每条须有依据——来自 yuangon_pack_excerpt 中路径或职责，或标注「外部检索」并对应 research_context；**编号列表**，写法同上）
## 风险或依赖（可选）
（0～3 句）
禁止编造研究摘要与节选中均未出现的版本号、文件名或内部政策。"""


def _daily_brief_strict_grounding() -> bool:
    return (
        os.environ.get("MODSTORE_DAILY_BRIEF_STRICT_GROUNDING", "0") or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def daily_brief_task_text() -> str:
    """当前环境下每日岗位简报使用的任务文案（测试与运维核对）。"""
    if _daily_brief_strict_grounding():
        return DAILY_BRIEF_TASK_STRICT
    return DAILY_BRIEF_TASK


BRIEF_TODO_HEADING = "## 待办任务"


def split_brief_markdown(text: str) -> Tuple[str, str]:
    """从简报正文中拆出「## 待办任务」区块；其余合并回主文（含该节之后的其它 ``##`` 章节）。"""
    m = re.search(rf"^{re.escape(BRIEF_TODO_HEADING)}\s*\n", text, re.M)
    if not m:
        return text.strip(), ""
    head = text[: m.start()].strip()
    tail = text[m.end() :]
    m2 = re.search(r"^## ", tail, re.M)
    if m2:
        todo_body = tail[: m2.start()].strip()
        rest = tail[m2.start() :].strip()
        main = (head + "\n\n" + rest).strip() if rest else head
    else:
        todo_body = tail.strip()
        main = head
    return main, todo_body


def _format_todo_section_html(todo_md: str) -> str:
    lines = [ln.strip() for ln in todo_md.splitlines() if ln.strip()]
    if not lines:
        return ""
    items = "".join(f'<li style="margin:4px 0">{html.escape(ln)}</li>' for ln in lines)
    return (
        '<div style="margin-top:12px;padding-top:10px;border-top:1px dashed #e5e7eb">'
        '<div style="font-size:13px;font-weight:600;color:#1e293b;margin-bottom:6px">待办事项</div>'
        f'<ul style="margin:0;padding-left:18px;font-size:13px;color:#334155">{items}</ul>'
        "</div>"
    )


def daily_brief_enabled() -> bool:
    return os.environ.get("MODSTORE_DAILY_BRIEF_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _daily_brief_todo_dispatch_immediate() -> bool:
    return os.environ.get(
        "MODSTORE_DAILY_BRIEF_TODO_DISPATCH_IMMEDIATE", "1"
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _daily_brief_user_id() -> int:
    """简报用的用户 ID：纳入该用户名下知识库集合的 RAG 可见范围（缺省 ``0``）。"""
    raw = (os.environ.get("MODSTORE_DAILY_BRIEF_USER_ID") or "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return 0


def _env_brief_seed_override(pkg_id: str) -> str | None:
    raw = (os.environ.get("MODSTORE_DAILY_BRIEF_SEEDS_JSON") or "").strip()
    if not raw:
        return None
    try:
        m = json.loads(raw)
        if isinstance(m, dict) and pkg_id in m:
            s = str(m.get(pkg_id) or "").strip()
            return s or None
    except json.JSONDecodeError:
        logger.warning("MODSTORE_DAILY_BRIEF_SEEDS_JSON is not valid JSON")
    return None


def resolve_daily_brief_research_brief(pkg_id: str, display_name: str) -> str:
    """调研 query 种子：``MODSTORE_DAILY_BRIEF_SEEDS_JSON`` 覆盖 manifest metadata，最后回退通用句式。"""
    o = _env_brief_seed_override(pkg_id)
    if o:
        return o
    try:
        sf = get_session_factory()
        with sf() as session:
            pack = load_employee_pack(session, pkg_id)
        man = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        v2 = (
            man.get("employee_config_v2")
            if isinstance(man.get("employee_config_v2"), dict)
            else {}
        )
        meta = v2.get("metadata") if isinstance(v2.get("metadata"), dict) else {}
        for key in ("daily_brief_seed", "daily_brief_research_focus"):
            v = meta.get(key)
            if v and str(v).strip():
                return str(v).strip()
    except RECOVERABLE_ERRORS:
        logger.debug("daily brief: manifest seed unavailable")
    return f"{display_name}（{pkg_id}）MODstore 运维、质量、发布与近期行业公开动态"


def _catalog_roster_pairs() -> List[Tuple[str, str]]:
    """编制内员工包：Postgres 或 XC ``packages.json`` 任一来源即可（不上架市场）。"""
    roster = all_planned_employee_ids()
    if not roster:
        return []
    from modstore_server.catalog_store import employee_pack_records_from_store

    xc = employee_pack_records_from_store()
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(CatalogItem.pkg_id, CatalogItem.name)
            .filter(CatalogItem.artifact == "employee_pack")
            .filter(CatalogItem.pkg_id.in_(list(roster)))
            .all()
        )
    name_by_id: Dict[str, str] = {}
    db_ids: set[str] = set()
    for r in rows:
        pid = str(r[0])
        db_ids.add(pid)
        name_by_id[pid] = str(r[1] or r[0])
    for pid in roster:
        if pid in xc and pid not in name_by_id:
            name_by_id[pid] = str(xc[pid].get("name") or pid).strip() or pid

    pairs: List[Tuple[str, str]] = []
    for pid in sorted(roster):
        if pid not in db_ids and pid not in xc:
            continue
        pairs.append((pid, name_by_id.get(pid, pid)))
    max_n = max(1, int(os.environ.get("MODSTORE_DAILY_BRIEF_MAX", "16")))
    return pairs[:max_n]


async def _one_brief_html(pkg_id: str, display_name: str, prov: str, mdl: str) -> str:
    uid = _daily_brief_user_id()
    brief_seed = resolve_daily_brief_research_brief(pkg_id, display_name)
    try:
        rc = await build_research_context(
            brief=brief_seed,
            intent="employee",
            max_repos=2,
            max_chars=6000,
            max_web=6,
            user_id=uid,
            rate_limit_bucket="daily_digest",
        )
        pack = ""
        warns: List[str] = []
        if rc.get("ok"):
            pack = str(rc.get("context_pack") or "")
            warns = list(rc.get("warnings") or [])
        else:
            warns = [str(rc.get("error") or "research failed")]
        excerpt, yg_warns = collect_yuangon_pack_excerpt(pkg_id)
        if yg_warns:
            warns.extend(yg_warns)
        inp = {
            "research_context": pack,
            "research_warnings": warns,
            "daily_brief_research_focus": brief_seed,
            "employee_label": display_name,
            "employee_id": pkg_id,
            "yuangon_pack_excerpt": excerpt,
            # 定时/服务端简报编排：允许含 shell_exec 等 high-risk handler 的员工完成 cognition/actions。
            "allow_high_risk_real_run": True,
        }
        _hr_gate = (os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()
        if _hr_gate:
            inp["high_risk_gate_token"] = _hr_gate

        def _run():
            return execute_employee_task(
                pkg_id,
                daily_brief_task_text(),
                inp,
                uid,
                bench_llm_override=(prov, mdl),
            )

        out = await asyncio.to_thread(_run)
        text = (out.get("reasoning_excerpt") or "").strip()
        cog_err = (out.get("cognition_error") or "").strip()
        warn_html = ""
        if warns:
            warn_html = (
                '<p style="color:#92400e;font-size:12px;margin:0 0 6px"><strong>调研提示：</strong> '
                f"{html.escape('; '.join(warns)[:800])}</p>"
            )
        if cog_err and not text:
            inner = (
                warn_html
                + f'<p style="color:#b91c1c;font-size:13px"><strong>模型不可用或调用失败。</strong> '
                f"{html.escape(cog_err)}</p>"
                '<p style="color:#64748b;font-size:12px">请检查平台 LLM Key、MODSTORE_EMPLOYEE_BENCH_* 与网络。</p>'
            )
        elif text:
            main_md, todo_md = split_brief_markdown(text)
            todo_block = _format_todo_section_html(todo_md)
            todo_sync_note = ""
            if todo_md.strip():
                try:
                    from modstore_server.employee_autonomy_service import (
                        dispatch_pending_brief_tasks,
                        enqueue_daily_brief_todos,
                    )

                    source_ref = datetime.now(UTC).strftime("%Y-%m-%d")
                    enq = enqueue_daily_brief_todos(
                        owner_employee_id=pkg_id,
                        todo_markdown=todo_md,
                        source_ref=source_ref,
                        payload={
                            "kind": "daily_brief_todo",
                            "employee_id": pkg_id,
                            "employee_label": display_name,
                        },
                    )
                    created = int(enq.get("created") or 0)
                    dispatched = 0
                    if created > 0 and _daily_brief_todo_dispatch_immediate():
                        d = dispatch_pending_brief_tasks(limit=max(1, min(created, 8)))
                        dispatched = int(d.get("done") or 0)
                    if created > 0:
                        todo_sync_note = (
                            '<p style="margin:6px 0 0;color:#0f766e;font-size:11px">'
                            f"待办已入队：{created} 条"
                            + (
                                f"，已触发调度完成 {dispatched} 条"
                                if dispatched > 0
                                else ""
                            )
                            + "</p>"
                        )
                except RECOVERABLE_ERRORS:
                    logger.error("daily brief todo enqueue failed")
            inner = (
                warn_html
                + f'<pre style="white-space:pre-wrap;font-size:13px">{html.escape(main_md)}</pre>'
                + todo_block
                + todo_sync_note
            )
        else:
            inner = warn_html + '<p style="color:#888;font-size:13px">（无输出）</p>'
    except BOUNDARY_ERRORS:  # noqa: BLE001
        logger.error("daily brief failed")
        inner = '<p style="color:#b91c1c;font-size:13px">生成简报失败</p>'

    title_esc = html.escape(display_name)
    pid_esc = html.escape(pkg_id)
    return (
        '<section style="margin-top:14px;padding:10px;border:1px solid #e5e7eb;border-radius:8px">'
        f'<h4 style="margin:0 0 8px;font-size:15px">{title_esc} <code>{pid_esc}</code></h4>{inner}'
        "</section>"
    )


async def build_daily_brief_html_async() -> str:
    if not daily_brief_enabled():
        return ""

    prov, mdl = resolve_platform_bench_llm()
    if not prov or not mdl:
        return (
            '<div style="margin-top:16px"><p style="color:#888;font-size:14px">'
            "<em>每日岗位方案：平台 Bench LLM 未配置（请配置平台 API Key 或 MODSTORE_EMPLOYEE_BENCH_*），已跳过。</em>"
            "</p></div>"
        )

    pairs = _catalog_roster_pairs()
    if not pairs:
        return (
            '<div style="margin-top:16px"><p style="color:#888;font-size:14px">'
            "<em>每日岗位方案：catalog 中与编制交集为空。</em>"
            "</p></div>"
        )

    sem = asyncio.Semaphore(3)

    async def _wrapped(pid: str, nm: str) -> str:
        async with sem:
            return await _one_brief_html(pid, nm, prov, mdl)

    sections = await asyncio.gather(*[_wrapped(p, n) for p, n in pairs])
    body = "".join(sections)
    return (
        '<div style="margin-top:18px">'
        '<h3 style="color:#1e3a5f;margin-bottom:8px">各岗位：工作内容摘要与新方案（catalog ∩ 编制）</h3>'
        f"{body}"
        "</div>"
    )


def build_daily_brief_html_sync() -> str:
    from modstore_server.runtime_async import run_coro_sync

    return run_coro_sync(build_daily_brief_html_async())
