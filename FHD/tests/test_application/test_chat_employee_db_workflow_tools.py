from unittest.mock import patch


def test_workflow_registry_exposes_employee_and_business_db_tools():
    from app.application.workflow.planner import get_tool_registry as get_planner_registry
    from app.services.tools_execution.registry import get_workflow_tool_registry

    workflow_registry = get_workflow_tool_registry()
    planner_registry = get_planner_registry()

    assert "employee" in workflow_registry
    assert "execute" in workflow_registry["employee"]["actions"]
    assert "business_db" in workflow_registry
    assert "read" in workflow_registry["business_db"]["actions"]
    assert "write" in workflow_registry["business_db"]["actions"]

    assert "employee" in planner_registry
    assert "business_db" in planner_registry


def test_fallback_planner_can_route_to_named_employee_without_llm():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch.object(LLMWorkflowPlanner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={
                "employee_pack_tools": [{"pack_id": "quality-validator"}],
                "registered_tool_count": 1,
            },
        ),
    ):
        planner = LLMWorkflowPlanner()
        plan = planner.plan(
            "u1",
            "call employee quality-validator to inspect this package",
            get_workflow_tool_registry(),
        )

    assert plan.intent == "employee_dispatch"
    assert plan.nodes[0].tool_id == "employee"
    assert plan.nodes[0].action == "execute"
    assert plan.nodes[0].params["employee_id"] == "quality-validator"


def test_fallback_planner_routes_customer_db_write_without_llm():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch.object(LLMWorkflowPlanner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    ):
        planner = LLMWorkflowPlanner()
        plan = planner.plan(
            "u1",
            "请把客户 星光贸易 写入数据库",
            get_workflow_tool_registry(),
        )

    node = plan.nodes[0]
    assert plan.intent == "business_db_write"
    assert node.tool_id == "business_db"
    assert node.action == "write"
    assert node.params["entity"] == "customers"
    assert node.params["operation"] == "upsert"
    assert node.params["payload"]["unit_name"] == "星光贸易"


def test_fallback_planner_routes_product_db_write_without_llm():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch.object(LLMWorkflowPlanner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    ):
        planner = LLMWorkflowPlanner()
        plan = planner.plan(
            "u1",
            "请把产品 5003A 添加到数据库，客户 星光贸易",
            get_workflow_tool_registry(),
        )

    node = plan.nodes[0]
    assert plan.intent == "business_db_write"
    assert node.tool_id == "business_db"
    assert node.action == "write"
    assert node.params["entity"] == "products"
    assert node.params["operation"] == "create"
    assert node.params["payload"]["name_or_model"] == "5003A"
    assert node.params["payload"]["unit_name"] == "星光贸易"


def test_fallback_planner_extracts_business_db_read_keyword_without_llm():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch.object(LLMWorkflowPlanner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    ):
        planner = LLMWorkflowPlanner()
        plan = planner.plan(
            "u1",
            "查数据库产品 XG-5003",
            get_workflow_tool_registry(),
        )

    node = plan.nodes[0]
    assert plan.intent == "business_db_read"
    assert node.tool_id == "business_db"
    assert node.action == "read"
    assert node.params["entity"] == "products"
    assert node.params["keyword"] == "XG-5003"


def test_fallback_planner_ignores_recoverable_memory_rag_error():
    from sqlalchemy.exc import OperationalError

    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    rag_error = OperationalError("CREATE EXTENSION", {}, Exception("sqlite does not support it"))
    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch.object(LLMWorkflowPlanner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=rag_error),
    ):
        planner = LLMWorkflowPlanner()
        plan = planner.plan("u1", "查数据库产品 XG-5003", get_workflow_tool_registry())

    assert plan.intent == "business_db_read"
    assert plan.nodes[0].tool_id == "business_db"


def test_employee_tool_dispatch_calls_local_employee_runtime():
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    with (
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={
                "employee_pack_tools": [{"pack_id": "quality-validator"}],
                "registered_tool_count": 1,
            },
        ),
        patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            return_value={"success": True, "result": {"summary": "ok"}},
        ) as mock_run,
    ):
        result = execute_registered_workflow_tool(
            "employee",
            "execute",
            {
                "employee_id": "quality-validator",
                "task": "inspect package",
                "_runtime_context": {"user_id": "42", "workspace_root": "/tmp/work"},
            },
        )

    assert result["success"] is True
    assert result["employee_id"] == "quality-validator"
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == "quality-validator"
    assert args[1] == "inspect package"
    assert kwargs["user_id"] == 42
    assert kwargs["workspace_root"] == "/tmp/work"


def test_business_db_read_routes_to_business_service_router():
    from app.services import tools_workflow_registered as mod

    with patch.object(
        mod,
        "_registered_router_products",
        return_value={"success": True, "data": [{"name": "A"}]},
    ) as mock_products:
        result = mod.execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "products", "keyword": "A", "_runtime_context": {"message": "read db"}},
        )

    assert result["success"] is True
    mock_products.assert_called_once()
    assert mock_products.call_args.args[0] == "query"
    assert mock_products.call_args.args[1]["keyword"] == "A"


def test_business_db_rejects_raw_sql():
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    result = execute_registered_workflow_tool(
        "business_db",
        "read",
        {"entity": "products", "sql": "select * from products"},
    )

    assert result["success"] is False
    assert "SQL" in result["message"]


def test_business_db_write_and_read_use_real_sqlite_services(monkeypatch, tmp_path):
    db_file = tmp_path / "business-tools.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    import app.db as db_mod
    from app.db.base import Base
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    db_mod.dispose_and_recreate_engine()
    Base.metadata.create_all(db_mod.engine, tables=[PurchaseUnit.__table__, Product.__table__])
    try:
        customer_name = "星光贸易集成测试"
        customer_write = execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": "customers",
                "operation": "upsert",
                "payload": {"unit_name": customer_name, "customer_name": customer_name},
            },
        )
        assert customer_write["success"] is True

        customer_read = execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "customers", "keyword": customer_name},
        )
        assert customer_read["success"] is True
        assert any(row.get("customer_name") == customer_name for row in customer_read["data"])

        product_write = execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": "products",
                "operation": "create",
                "payload": {
                    "unit_name": customer_name,
                    "name_or_model": "星光测试产品",
                    "product_name": "星光测试产品",
                    "model_number": "XG-5003",
                    "unit_price": 12.5,
                },
            },
        )
        assert product_write["success"] is True

        product_read = execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "products", "keyword": "XG-5003"},
        )
        assert product_read["success"] is True
        assert any(
            row.get("model_number") == "XG-5003" or row.get("name") == "星光测试产品"
            for row in product_read["data"]
        )
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=[Product.__table__, PurchaseUnit.__table__])
        db_mod.dispose_and_recreate_engine()


def test_chat_formats_employee_and_business_db_outputs():
    from unittest.mock import Mock

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    plan = PlanGraph(
        plan_id="p-tools",
        intent="employee_and_db",
        todo_steps=["run tools"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect"},
                risk="medium",
                idempotent=False,
                description="run employee",
            ),
            WorkflowNode(
                node_id="read_db",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003A"},
                risk="low",
                idempotent=True,
                description="read products",
            ),
        ],
        risk_level="medium",
    )
    employee_item = Mock()
    employee_item.success = True
    employee_item.node_id = "run_employee"
    employee_item.tool_id = "employee"
    employee_item.action = "execute"
    employee_item.output = {
        "success": True,
        "employee_id": "quality-validator",
        "message": "员工执行完成",
        "data": {"result": {"summary": "ok"}},
    }
    employee_item.error = ""

    db_item = Mock()
    db_item.success = True
    db_item.node_id = "read_db"
    db_item.tool_id = "business_db"
    db_item.action = "read"
    db_item.output = {"success": True, "data": [{"name": "A"}, {"name": "B"}]}
    db_item.error = ""

    run_result = Mock()
    run_result.success = True
    run_result.node_results = [employee_item, db_item]
    run_result.message = ""

    result = service._format_workflow_run_response(plan, run_result)

    assert "员工 quality-validator" in result["response"]
    assert "products 查询 2 条" in result["response"]
    node_results = result["data"]["data"]["node_results"]
    assert node_results[0]["message"] == "员工执行完成"
    assert "output_preview" in node_results[0]


def test_ai_chat_dynamic_workflow_executes_employee_tool():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-employee",
        intent="employee_dispatch",
        todo_steps=["run employee"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect package"},
                risk="medium",
                idempotent=False,
                description="run employee",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="test low enough",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="call quality-validator",
            source="pro",
            context={},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "employee ok",
            "data": {"done": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source="pro",
            context={},
            file_context={},
        )

    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    assert completed["data"]["action"] == "workflow_done"
    assert result is not None
    assert repo.get(result["run_id"]).status == "completed"
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "employee"
    assert action == "execute"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_explicit_business_db_read_uses_agent_orchestrator():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-read-agent",
        intent="business_db_read",
        todo_steps=["read products"],
        nodes=[
            WorkflowNode(
                node_id="read_products",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003"},
                risk="low",
                idempotent=True,
                description="read products",
            )
        ],
        risk_level="low",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "5003"}]},
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="low risk",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="查数据库产品 5003",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    assert result["success"] is True
    assert result["data"]["action"] == "workflow_done"
    assert result["run_id"]
    assert result["data"]["data"]["run_id"] == result["run_id"]
    assert repo.get(result["run_id"]) is not None
    mock_dispatch.assert_called_once()
    tool_id, action, _params = mock_dispatch.call_args.args
    assert tool_id == "business_db"
    assert action == "read"


def test_ai_chat_pro_low_risk_dynamic_workflow_uses_agent_orchestrator():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-pro-product-query",
        intent="product_lookup",
        todo_steps=["query products"],
        nodes=[
            WorkflowNode(
                node_id="query_products",
                tool_id="products",
                action="query",
                params={"keyword": "5003"},
                risk="low",
                idempotent=True,
                description="query products",
            )
        ],
        risk_level="low",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.application.normal_chat_dispatch.route_normal_mode_message",
            return_value={"intent": "unknown"},
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "5003"}]},
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="low risk",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])
        service.workflow_engine.run = Mock()

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="查 5003 产品",
            source="pro",
            context={},
            file_context={},
        )

    assert result is not None
    assert result["success"] is True
    assert result["data"]["action"] == "workflow_done"
    assert result["run_id"]
    assert result["data"]["data"]["run_id"] == result["run_id"]
    run = repo.get(result["run_id"])
    assert run is not None
    assert run.plan_id == "p-pro-product-query"
    assert run.status == "completed"
    assert run.metadata["runtime_context"]["workflow_trace_mode"] == "agent_orchestrator"
    assert run.metadata["runtime_context"]["dynamic_workflow"] is True
    assert run.metadata["runtime_context"]["source"] == "pro"
    service.workflow_engine.run.assert_not_called()
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "products"
    assert action == "query"
    assert params["_runtime_context"]["run_id"] == result["run_id"]
    assert params["_runtime_context"]["source"] == "pro"


def test_workflow_engine_does_not_retry_non_idempotent_write():
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import PlanGraph, WorkflowNode

    calls = {"count": 0}

    def dispatch(tool_id, action, params):
        calls["count"] += 1
        return {"success": False, "message": "db busy after partial write"}

    engine = WorkflowEngine(tool_dispatcher=dispatch)
    plan = PlanGraph(
        plan_id="p-write",
        intent="write_db",
        nodes=[
            WorkflowNode(
                node_id="write_product",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "products",
                    "operation": "create",
                    "payload": {"name_or_model": "5003A"},
                },
                risk="medium",
                idempotent=False,
            )
        ],
        risk_level="medium",
    )

    result = engine.run(plan, max_retries=3)

    assert result.success is False
    assert calls["count"] == 1
    node_result = result.node_results[0]
    assert node_result.retryable is False
    assert node_result.retries == 0
    assert "副作用" in node_result.recovery_hint
    assert result.final_context["workflow_status"]["failed_node_id"] == "write_product"
    assert result.final_context["workflow_trace"][0]["retryable"] is False


def test_workflow_engine_retries_idempotent_write_once_then_succeeds():
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import WorkflowNode

    calls = {"count": 0}

    def dispatch(tool_id, action, params):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": False, "message": "temporary lock"}
        return {"success": True, "message": "customer upserted"}

    engine = WorkflowEngine(tool_dispatcher=dispatch)
    node = WorkflowNode(
        node_id="upsert_customer",
        tool_id="business_db",
        action="write",
        params={
            "entity": "customers",
            "operation": "upsert",
            "payload": {"unit_name": "星光贸易"},
        },
        risk="medium",
        idempotent=True,
    )

    result = engine._run_node(node, {}, max_retries=2)

    assert result.success is True
    assert calls["count"] == 2
    assert result.retryable is True
    assert result.retries == 1
    assert len(result.attempts) == 2


def test_agentic_loop_uses_action_name_and_disables_write_retry():
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import PlanGraph

    calls = []

    def dispatch(tool_id, action, params):
        calls.append((tool_id, action))
        return {"success": False, "message": "write rejected"}

    engine = WorkflowEngine(tool_dispatcher=dispatch)
    call_count = {"n": 0}

    def decide(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "action": "execute",
                "tool_id": "business_db",
                "action_name": "write",
                "params": {"entity": "products", "operation": "create", "payload": {}},
                "reasoning": "write product",
            }
        return {"action": "done"}

    with patch.object(engine, "_llm_decide_next_step", side_effect=decide):
        result = engine.run(
            PlanGraph(plan_id="p-agentic", intent="agentic"),
            runtime_context={"message": "create product"},
            max_retries=2,
            agentic_loop=True,
            tool_registry={
                "business_db": {
                    "actions": {"write": {"risk": "medium", "idempotent": False}}
                }
            },
        )

    assert calls == [("business_db", "write")]
    assert result.node_results[0].retryable is False
    assert "副作用" in result.node_results[0].recovery_hint


def test_ai_chat_agentic_excel_loop_returns_agent_run_trace():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import NodeExecutionResult, PlanGraph, WorkflowRunResult

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-agentic-excel",
        intent="excel_agentic_analysis",
        todo_steps=["inspect excel"],
    )
    run_result = WorkflowRunResult(
        plan_id="p-agentic-excel",
        success=True,
        node_results=[
            NodeExecutionResult(
                node_id="agent_excel_analysis_query",
                success=True,
                tool_id="excel_analysis",
                action="query",
                params={"file_path": "/tmp/demo.xlsx", "question": "查价格"},
                output={
                    "success": True,
                    "message": "Excel 分析完成",
                    "artifacts": [
                        {
                            "artifact_type": "excel_query_result",
                            "name": "demo.xlsx",
                            "source": "excel_analysis.query",
                            "summary": "价格列已识别",
                        }
                    ],
                },
                duration_ms=7,
            )
        ],
        final_context={"workflow_status": {"state": "completed"}},
        message="AgenticLoop 完成（2 步）",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.application.normal_chat_dispatch.route_normal_mode_message",
            return_value={"intent": "unknown"},
        ),
        patch(
            "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="excel agentic",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])
        service.workflow_engine.run = Mock(return_value=run_result)

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="分析这个 Excel 下一步",
            source="pro",
            context={"excel_analysis": {"file_path": "/tmp/demo.xlsx"}},
            file_context={},
        )

    assert result is not None
    assert result["success"] is True
    assert result["data"]["action"] == "workflow_done"
    assert result["run_id"]
    runtime_context = service.workflow_engine.run.call_args.kwargs["runtime_context"]
    assert runtime_context["run_id"] == result["run_id"]
    assert runtime_context["agent_run_id"] == result["run_id"]

    run = repo.get(result["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.metadata["trace_mode"] == "agentic_loop_bridge"
    assert run.metadata["tool_call_count"] == 1
    assert run.metadata["artifact_count"] == 1
    assert run.tool_calls[0].tool_id == "excel_analysis"
    assert run.tool_calls[0].action == "query"
    assert run.tool_calls[0].params["file_path"] == "/tmp/demo.xlsx"
    assert run.artifacts[0].artifact_type == "excel_query_result"
    assert result["data"]["data"]["tool_call_count"] == 1
    assert result["data"]["data"]["artifact_count"] == 1


def test_chat_formats_recovery_hint_for_non_retryable_failure():
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import NodeExecutionResult, PlanGraph, WorkflowNode

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    plan = PlanGraph(
        plan_id="p-fail",
        intent="business_db_write",
        nodes=[
            WorkflowNode(
                node_id="write_product",
                tool_id="business_db",
                action="write",
                params={"entity": "products", "operation": "create", "payload": {}},
                risk="medium",
                idempotent=False,
            )
        ],
        risk_level="medium",
    )
    run_result = type(
        "RunResult",
        (),
        {
            "success": False,
            "message": "节点 write_product 执行失败",
            "node_results": [
                NodeExecutionResult(
                    node_id="write_product",
                    success=False,
                    tool_id="business_db",
                    action="write",
                    output={"success": False, "message": "db busy"},
                    error="db busy",
                    retryable=False,
                    recovery_hint="请核对数据库状态后手动重试。",
                    duration_ms=3,
                )
            ],
            "final_context": {
                "workflow_status": {"state": "failed"},
                "workflow_trace": [{"node_id": "write_product"}],
            },
        },
    )()

    result = service._format_workflow_run_response(plan, run_result)

    assert "未自动重试" in result["response"]
    assert "恢复建议" in result["response"]
    node_result = result["data"]["data"]["node_results"][0]
    assert node_result["retryable"] is False
    assert node_result["recovery_hint"] == "请核对数据库状态后手动重试。"
    assert result["data"]["data"]["workflow_status"]["state"] == "failed"


def test_ai_chat_explicit_employee_intent_runs_without_pro_source():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-employee-normal",
        intent="employee_dispatch",
        todo_steps=["run employee"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect package"},
                risk="medium",
                idempotent=False,
                description="run employee",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="explicit employee intent",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="调用员工 quality-validator 检查这个包",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "employee ok",
            "data": {"done": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "employee"
    assert action == "execute"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_explicit_business_db_intent_skips_excel_shortcut_without_pro_source():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-normal",
        intent="business_db_write",
        todo_steps=["write customer"],
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "upsert",
                    "payload": {"unit_name": "星光贸易"},
                },
                risk="medium",
                idempotent=True,
                description="write customer",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                blocking_nodes=[],
                reason="explicit db intent",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "客户已写入",
            "data": {"created": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    assert "Excel 分析上下文" not in result["response"]
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "business_db"
    assert action == "write"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_medium_risk_confirmation_continues_same_agent_run():
    from unittest.mock import Mock

    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-confirm-agent",
        intent="business_db_write",
        todo_steps=["write customer"],
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "upsert",
                    "payload": {"unit_name": "星光贸易"},
                },
                risk="medium",
                idempotent=True,
                description="write customer",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=True,
                blocking_nodes=["write_customer"],
                reason="explicit db write needs confirmation",
            )
        )
        service.approval_service.get_approval_required_nodes = Mock(return_value=[])

        waiting = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

        assert waiting is not None
        assert waiting["data"]["action"] == "workflow_confirmation_required"
        assert waiting["run_id"]
        assert repo.get(waiting["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {"success": True, "message": "客户已写入"}
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source=None,
            context={"tool_execution_profile": "normal"},
            file_context={},
        )

    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == waiting["run_id"]
    assert completed["data"]["action"] == "workflow_done"
    run = repo.get(waiting["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert "step.approved" in [event.event_type for event in run.events]
    mock_dispatch.assert_called_once()
