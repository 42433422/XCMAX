#!/usr/bin/env python3
"""AI Agent V0 CLI：自然语言 → plan → HybridRiskGate → WorkflowEngine.run（只读查询链 demo）。

用法（在 FHD 根目录）::

    python3 scripts/ai_agent_v0/run_demo.py
    python3 scripts/ai_agent_v0/run_demo.py --message "查一下七彩乐园有哪些产品"
    python3 scripts/ai_agent_v0/run_demo.py --dry-plan

证据写入 ``docs/evidence/ai-agent-v0/demo-run-YYYYMMDD.json``。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "ai-agent-v0"
DEFAULT_MESSAGE = "查一下七彩乐园有哪些产品"
DEFAULT_USER_ID = "ai_agent_v0_demo"


class _DemoUserMemoryRagStub:
    def query(self, **_kwargs: Any) -> dict[str, Any]:
        return {"hits": []}

    def format_for_prompt(self, **_kwargs: Any) -> str:
        return ""


def _stub_planner_rag() -> None:
    """避免 demo CLI 强依赖 PG 向量库（与 planner.plan 内 try/except 意图一致）。"""
    import app.application as app_pkg
    import app.application.user_memory_vector_app_service as rag_mod

    def _stub_factory() -> _DemoUserMemoryRagStub:
        return _DemoUserMemoryRagStub()

    rag_mod.get_user_memory_rag_app_service = _stub_factory  # type: ignore[method-assign]
    app_pkg.get_user_memory_rag_app_service = _stub_factory  # type: ignore[attr-defined]


def _mock_tool_dispatcher(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    """无 DB 时的工具桩：仍经 WorkflowEngine 调度，非手写 node_results。"""
    _ = params
    if tool_id == "customers" and action == "query":
        return {
            "success": True,
            "data": [{"unit_name": "七彩乐园", "id": 1}],
        }
    if tool_id == "products" and action == "query":
        return {
            "success": True,
            "data": [
                {
                    "name": "9803",
                    "model_number": "9803",
                    "unit": "七彩乐园",
                }
            ],
        }
    return {"success": False, "message": f"mock 未实现: {tool_id}.{action}"}


def _bootstrap() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
        local_demo_env = ROOT / "scripts" / "ai_agent_v0" / "demo.local.env"
        if local_demo_env.is_file():
            load_dotenv(local_demo_env, override=True)
    except ImportError:
        pass


def _dispatch_workflow_tool(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    from app.routes.tools import execute_registered_workflow_tool

    return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)


def _database_reachable() -> bool:
    url = str(os.getenv("DATABASE_URL") or "").strip()
    if not url or url.startswith("sqlite"):
        return bool(url)
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _resolve_execution_mode() -> tuple[str, Any]:
    """live=真实工具；mock=无 DB 时经 WorkflowEngine 的桩调度（仍非手写 node_results）。"""
    force_mock = os.getenv("AI_AGENT_V0_MOCK_TOOLS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    force_live = os.getenv("AI_AGENT_V0_LIVE_TOOLS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if force_mock:
        return "mock", _mock_tool_dispatcher
    if force_live or _database_reachable():
        return "live", _dispatch_workflow_tool
    return "mock", _mock_tool_dispatcher


def _merge_runtime_context(
    user_id: str, message: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}
    if isinstance(context, dict):
        for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
            if key in context and context[key] is not None:
                runtime_ctx[key] = context[key]
    return runtime_ctx


def _detect_planner_mode(plan: Any) -> str:
    metadata = getattr(plan, "metadata", None) or {}
    planner = str(metadata.get("planner") or "").strip().lower()
    if planner == "fallback":
        return "fallback"
    if planner in {"llm", "critic_repair", "react"} or "llm" in planner:
        return "llm"
    return "fallback"


def _node_to_dict(node: Any) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "tool_id": node.tool_id,
        "action": node.action,
        "risk": node.risk,
        "depends_on": list(node.depends_on or []),
        "params": dict(node.params or {}),
    }


def _summarize_output(output: Any, *, max_len: int = 400) -> Any:
    if not isinstance(output, dict):
        text = str(output)
        return text[:max_len] if len(text) > max_len else text
    summary: dict[str, Any] = {}
    if "success" in output:
        summary["success"] = output.get("success")
    if "message" in output:
        summary["message"] = str(output.get("message") or "")[:200]
    data = output.get("data")
    if isinstance(data, list):
        summary["data_count"] = len(data)
        if data and isinstance(data[0], dict):
            keys = list(data[0].keys())[:6]
            summary["data_sample_keys"] = keys
    elif data is not None:
        summary["data_preview"] = str(data)[:max_len]
    for key in ("unit_name", "exists", "created", "matched_count"):
        if key in output:
            summary[key] = output[key]
    return summary or {k: output[k] for k in list(output.keys())[:8]}


def _build_evidence(
    *,
    input_message: str,
    plan: Any,
    planner_mode: str,
    plan_validation_error: str | None,
    risk_decision: Any,
    run_result: Any | None,
    dry_plan: bool,
    execution_mode: str,
) -> dict[str, Any]:
    nodes = [_node_to_dict(n) for n in (plan.nodes or [])]
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_message": input_message,
        "execution_mode": execution_mode,
        "planner_mode": planner_mode,
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "risk_level": plan.risk_level,
        "nodes": nodes,
        "plan_validation_error": plan_validation_error,
        "risk_gate": {
            "requires_confirmation": bool(risk_decision.requires_confirmation),
            "blocking_nodes": list(risk_decision.blocking_nodes or []),
            "reason": str(risk_decision.reason or ""),
        },
        "dry_plan": dry_plan,
    }
    if dry_plan:
        payload["success"] = False
        payload["message"] = "dry-plan：仅规划，未执行 engine.run"
        return payload

    if run_result is None:
        payload["success"] = False
        payload["message"] = "未执行（门控需确认或缺少 run_result）"
        return payload

    payload["success"] = bool(run_result.success)
    payload["message"] = str(run_result.message or "")
    payload["node_results_summary"] = [
        {
            "node_id": item.node_id,
            "tool_id": item.tool_id,
            "action": item.action,
            "success": bool(item.success),
            "error": str(item.error or "")[:200],
            "output_summary": _summarize_output(item.output),
        }
        for item in (run_result.node_results or [])
    ]
    return payload


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return EVIDENCE_DIR / f"demo-run-{stamp}.json"


def run_demo(
    message: str,
    *,
    user_id: str = DEFAULT_USER_ID,
    dry_plan: bool = False,
    mock_tools: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.risk_gate import HybridRiskGate
    from app.application.workflow.types import validate_plan_graph
    from app.routes.tools import get_workflow_tool_registry

    _stub_planner_rag()

    tool_registry = get_workflow_tool_registry()
    planner = LLMWorkflowPlanner()
    risk_gate = HybridRiskGate()
    if mock_tools:
        execution_mode, dispatcher = "mock", _mock_tool_dispatcher
    else:
        execution_mode, dispatcher = _resolve_execution_mode()
    engine = WorkflowEngine(tool_dispatcher=dispatcher)

    plan = planner.plan(
        user_id=user_id,
        message=message,
        tool_registry=tool_registry,
        context={"tool_execution_profile": "normal"},
    )
    planner_mode = _detect_planner_mode(plan)
    plan_validation_error = validate_plan_graph(plan)
    decision = risk_gate.evaluate(plan=plan, context={})
    runtime_ctx = _merge_runtime_context(user_id, message, context={"tool_execution_profile": "normal"})

    run_result = None
    if not dry_plan and not decision.requires_confirmation:
        run_result = engine.run(
            plan=plan,
            runtime_context=runtime_ctx,
            max_retries=1,
            agentic_loop=False,
            tool_registry=tool_registry,
            user_id=user_id,
        )

    evidence = _build_evidence(
        input_message=message,
        plan=plan,
        planner_mode=planner_mode,
        plan_validation_error=plan_validation_error,
        risk_decision=decision,
        run_result=run_result,
        dry_plan=dry_plan,
        execution_mode=execution_mode,
    )

    out = output_path or _default_output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["_evidence_path"] = str(out)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent V0 只读查询链 demo")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="用户自然语言输入")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="demo 用户 ID")
    parser.add_argument(
        "--dry-plan",
        action="store_true",
        help="仅规划与门控，不执行 WorkflowEngine.run",
    )
    parser.add_argument(
        "--mock-tools",
        action="store_true",
        help="工具走内存桩（无 DATABASE_URL 时用于留证；仍经 WorkflowEngine）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="证据 JSON 路径（默认 docs/evidence/ai-agent-v0/demo-run-YYYYMMDD.json）",
    )
    args = parser.parse_args(argv)

    _bootstrap()
    force_live = str(os.environ.get("AI_AGENT_V0_LIVE_TOOLS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    mock_tools = bool(args.mock_tools) or (
        str(os.environ.get("AI_AGENT_V0_MOCK_TOOLS", "")).strip().lower()
        in {"1", "true", "yes"}
    )
    if not mock_tools and not force_live and not _database_reachable():
        mock_tools = True
    evidence = run_demo(
        str(args.message or DEFAULT_MESSAGE).strip() or DEFAULT_MESSAGE,
        user_id=str(args.user_id or DEFAULT_USER_ID),
        dry_plan=bool(args.dry_plan),
        mock_tools=mock_tools,
        output_path=args.output,
    )

    path = evidence.pop("_evidence_path", "")
    print(f"planner_mode={evidence.get('planner_mode')} success={evidence.get('success')}")
    print(f"plan_id={evidence.get('plan_id')} nodes={len(evidence.get('nodes') or [])}")
    if path:
        print(f"evidence: {path}")

    if args.dry_plan:
        return 0
    return 0 if evidence.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
