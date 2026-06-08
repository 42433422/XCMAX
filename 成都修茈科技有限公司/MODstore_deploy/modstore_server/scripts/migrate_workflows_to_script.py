"""把节点图工作流迁移成脚本工作流（``ScriptWorkflow``）的后台 worker。

主流程：

1. 拉取 ``Workflow`` 表里 ``migration_status`` 为空 / ``pending`` 的行；
2. 读取该 workflow 的 nodes / edges / triggers，拼出一份**结构化 Brief**；
3. 用 :func:`script_agent.agent_loop.run_agent_loop` 跑完整代理流水线（context →
   plan → code → static-check → sandbox-run → observer → 失败修复 → 通过则交付）；
4. 通过：写新 ``ScriptWorkflow`` 行，状态 = ``sandbox_testing``；
   失败：``Workflow.migration_status = "failed"``，原行不动。

原触发器（cron / webhook）**保留在 ``WorkflowTrigger`` 表**不动；当用户在
新工作流上点 "启用" 时，触发器目标 ID 才被切到新脚本工作流（这步在 API 层完成）。

可作为 CLI 直接调用::

    python -m modstore_server.scripts.migrate_workflows_to_script --user-id 5
    python -m modstore_server.scripts.migrate_workflows_to_script --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.llm_key_resolver import resolve_api_key, resolve_base_url
from modstore_server.models import (
    ScriptWorkflow,
    ScriptWorkflowVersion,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowTrigger,
    get_session_factory,
)
from modstore_server.script_agent.agent_loop import run_agent_loop
from modstore_server.script_agent.brief import Brief, BriefInputFile
from modstore_server.script_agent.llm_client import LlmClient, RealLlmClient

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    workflow_id: int
    ok: bool
    new_workflow_id: Optional[int] = None
    iterations: int = 0
    error: str = ""


# ----------------------------- helpers ----------------------------- #


def _safe_load_json(raw: str) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _summarize_node(node: WorkflowNode) -> str:
    cfg = _safe_load_json(node.config)
    cfg_brief = ""
    if isinstance(cfg, dict):
        keys = list(cfg.keys())[:6]
        cfg_brief = ", ".join(f"{k}={cfg[k]!r}" for k in keys if cfg[k] is not None)
        if len(cfg) > 6:
            cfg_brief += ", …"
    return f"#{node.id} type={node.node_type} name={node.name!r} config={{{cfg_brief}}}"


def _summarize_trigger(trigger: WorkflowTrigger) -> str:
    cfg = _safe_load_json(trigger.config_json)
    return f"type={trigger.trigger_type} key={trigger.trigger_key} active={trigger.is_active} config={cfg}"


def build_brief_from_workflow(db: Session, workflow: Workflow) -> Brief:
    """读取节点图，拼成一个还行的 Brief。

    特意把所有节点 + 边 + 触发器原原本本写进 goal 里，让 agent loop 能看到
    "原图"。LLM 通常能从这里推断出输出契约；剩下的细节通过 acceptance 兜底。
    """
    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow.id)
        .order_by(WorkflowNode.id.asc())
        .all()
    )
    edges = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == workflow.id)
        .order_by(WorkflowEdge.id.asc())
        .all()
    )
    triggers = (
        db.query(WorkflowTrigger)
        .filter(WorkflowTrigger.workflow_id == workflow.id)
        .order_by(WorkflowTrigger.id.asc())
        .all()
    )

    node_lines = [_summarize_node(n) for n in nodes] or ["(无)"]
    edge_lines = [
        f"{e.source_node_id} -> {e.target_node_id} cond={e.condition!r}" for e in edges
    ] or ["(无)"]
    trigger_lines = [_summarize_trigger(t) for t in triggers] or ["(无)"]

    goal = (
        f"将旧节点图工作流 #{workflow.id}「{workflow.name}」迁移成等效 Python 脚本。\n\n"
        f"原描述：{(workflow.description or '').strip() or '(空)'}\n\n"
        "原图节点（按数据库 id 升序）：\n  - "
        + "\n  - ".join(node_lines)
        + "\n\n原图连接：\n  - "
        + "\n  - ".join(edge_lines)
        + "\n\n原触发器：\n  - "
        + "\n  - ".join(trigger_lines)
    )
    outputs = (
        "outputs/result.json，至少包含本工作流最终输出关键字段；"
        "若原图最后一节点是 employee/HTTP/通知类，则 result.json 应记录其调用结果与状态。"
    )
    acceptance = (
        "脚本运行返回码 0；至少产出 outputs/result.json，且该文件可被 json.loads 解析；"
        "stderr 不含 ERROR 级别日志。"
    )
    fallback = (
        "对原节点中无法 1:1 翻译的能力（如某些自定义条件、子工作流），"
        "请用 modstore_runtime.ai() 兜底推断；并在 outputs/migration_notes.md 里写下哪些节点降级处理。"
    )

    return Brief(
        goal=goal,
        outputs=outputs,
        acceptance=acceptance,
        inputs=[BriefInputFile(filename="(无上传文件，此为节点图迁移)", description="")],
        fallback=fallback,
        references={"migrated_from_workflow_id": workflow.id},
        trigger_type=str(triggers[0].trigger_type if triggers else "manual"),
    )


def _resolve_user_llm_for_migration(db: Session, user: User) -> Optional[Dict[str, Any]]:
    """读 ``user.default_llm_json`` 选 provider/model，否则返回 None（跳过迁移）。"""
    raw = (user.default_llm_json or "").strip()
    if not raw:
        return None
    try:
        prefs = json.loads(raw)
    except json.JSONDecodeError:
        return None
    provider = str(prefs.get("provider") or "").strip()
    model = str(prefs.get("model") or "").strip()
    if not provider or not model:
        return None
    api_key, _src = resolve_api_key(db, user.id, provider)
    if not api_key:
        return None
    base_url = resolve_base_url(db, user.id, provider)
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


# ----------------------------- 核心 ----------------------------- #


async def migrate_one(
    db: Session,
    workflow: Workflow,
    *,
    llm_factory: Callable[[Session, User], Optional[LlmClient]],
    sandbox_kwargs_factory: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> MigrationResult:
    """把单个 ``Workflow`` 迁移到 ``ScriptWorkflow``。

    ``llm_factory`` 注入便于测试；返回 ``None`` 表示该用户没有可用 LLM 配置 →
    迁移直接标记 ``failed``，不浪费 sandbox 资源。
    """
    user = db.query(User).filter(User.id == workflow.user_id).first()
    if not user:
        workflow.migration_status = "failed"
        db.commit()
        return MigrationResult(workflow.id, ok=False, error="user not found")

    llm = llm_factory(db, user)
    if llm is None:
        workflow.migration_status = "failed"
        db.commit()
        return MigrationResult(
            workflow.id, ok=False, error="user 缺少可用 LLM 配置（default_llm_json）"
        )

    workflow.migration_status = "migrating"
    db.commit()

    brief = build_brief_from_workflow(db, workflow)
    session_id = f"migrate_{workflow.id}_{int(datetime.now(timezone.utc).timestamp())}"
    sandbox_kwargs: Dict[str, Any] = {}
    if sandbox_kwargs_factory is not None:
        sandbox_kwargs = sandbox_kwargs_factory({})

    final_outcome: Optional[Dict[str, Any]] = None
    try:
        async for ev in run_agent_loop(
            brief,
            llm=llm,
            user_id=user.id,
            session_id=session_id,
            files=[],
            sandbox_kwargs=sandbox_kwargs,
        ):
            if ev.type in ("done", "error"):
                final_outcome = (ev.payload or {}).get("outcome") or {}
    except Exception as e:  # noqa: BLE001
        workflow.migration_status = "failed"
        db.commit()
        return MigrationResult(workflow.id, ok=False, error=f"agent loop crashed: {e}")

    if not final_outcome or not final_outcome.get("ok"):
        workflow.migration_status = "failed"
        db.commit()
        return MigrationResult(
            workflow.id,
            ok=False,
            iterations=int((final_outcome or {}).get("iterations") or 0),
            error=str((final_outcome or {}).get("error") or "agent loop did not converge"),
        )

    code = str(final_outcome.get("final_code") or "").strip()
    plan_md = str(final_outcome.get("plan_md") or "")
    new_wf = ScriptWorkflow(
        user_id=user.id,
        name=workflow.name,
        brief_json=json.dumps(asdict(brief), ensure_ascii=False),
        script_text=code,
        schema_in_json="{}",
        status="sandbox_testing",
        agent_session_id=session_id,
        migrated_from_workflow_id=workflow.id,
    )
    db.add(new_wf)
    db.commit()
    db.refresh(new_wf)

    version = ScriptWorkflowVersion(
        workflow_id=new_wf.id,
        version_no=1,
        script_text=code,
        plan_md=plan_md,
        agent_log_json=json.dumps(
            {
                "trace": final_outcome.get("trace") or [],
                "iterations": final_outcome.get("iterations"),
                "migrated_from_workflow_id": workflow.id,
            },
            ensure_ascii=False,
        ),
        is_current=True,
    )
    db.add(version)

    workflow.migration_status = "migrated"
    workflow.migrated_to_id = new_wf.id
    db.commit()

    return MigrationResult(
        workflow.id,
        ok=True,
        new_workflow_id=new_wf.id,
        iterations=int(final_outcome.get("iterations") or 0),
    )


async def migrate_user_workflows(
    user_id: Optional[int] = None,
    *,
    db: Optional[Session] = None,
    llm_factory: Optional[Callable[[Session, User], Optional[LlmClient]]] = None,
    sandbox_kwargs_factory: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    limit: Optional[int] = None,
) -> List[MigrationResult]:
    """批量迁移：未指定 ``user_id`` 时迁所有有未迁移行的用户。"""

    def _default_llm_factory(db_: Session, user_: User) -> Optional[LlmClient]:
        cfg = _resolve_user_llm_for_migration(db_, user_)
        if not cfg:
            return None
        return RealLlmClient(
            cfg["provider"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            base_url=cfg.get("base_url"),
        )

    factory = llm_factory or _default_llm_factory
    own_session = False
    if db is None:
        sf = get_session_factory()
        db = sf()
        own_session = True

    try:
        q = db.query(Workflow).filter(
            (Workflow.migration_status == "") | (Workflow.migration_status == "pending")
        )
        if user_id is not None:
            q = q.filter(Workflow.user_id == user_id)
        q = q.order_by(Workflow.id.asc())
        if limit:
            q = q.limit(int(limit))
        rows = q.all()

        results: List[MigrationResult] = []
        for wf in rows:
            try:
                r = await migrate_one(
                    db,
                    wf,
                    llm_factory=factory,
                    sandbox_kwargs_factory=sandbox_kwargs_factory,
                )
            except Exception as e:  # noqa: BLE001
                wf.migration_status = "failed"
                db.commit()
                r = MigrationResult(wf.id, ok=False, error=f"{type(e).__name__}: {e}")
            results.append(r)
            logger.info(
                "migrate workflow=%s ok=%s iters=%s err=%s",
                r.workflow_id,
                r.ok,
                r.iterations,
                r.error,
            )
        return results
    finally:
        if own_session:
            db.close()


# ----------------------------- CLI ----------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Migrate legacy node-graph workflows to script workflows."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--user-id", type=int, help="只迁移指定用户的工作流")
    g.add_argument("--all", action="store_true", help="迁移所有用户")
    p.add_argument("--limit", type=int, default=None, help="最多处理多少个 workflow")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    user_id = None if args.all else args.user_id
    results = asyncio.run(migrate_user_workflows(user_id=user_id, limit=args.limit))
    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok
    logger.info("migration done: ok=%s, fail=%s, total=%s", ok, fail, len(results))
    for r in results:
        logger.info(
            "  workflow=%s ok=%s new=%s iters=%s err=%s",
            r.workflow_id,
            r.ok,
            r.new_workflow_id,
            r.iterations,
            r.error,
        )
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
