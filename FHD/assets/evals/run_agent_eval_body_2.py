def _run_business_event_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.business_api import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "print_label").strip().lower() or "print_label"
    route_map = {
        "print_label": "/api/business/print/label",
        "inventory_update": "/api/business/inventory/update",
        "shipment_create": "/api/business/shipment/create",
    }
    path = route_map.get(action, "/api/business/print/label")
    body = dict(task.get("body") or {})
    if action == "print_label":
        body.setdefault("job_id", "print-job-eval")
        body.setdefault("document_name", "发货标签.pdf")
        body.setdefault("printer_id", "default")
        body.setdefault("copies", 1)
    elif action == "inventory_update":
        body.setdefault("product_id", "sku-1")
        body.setdefault("warehouse_id", "main")
        body.setdefault("delta", -2)
        body.setdefault("reason", "shipment")
        body.setdefault("new_quantity", 18)
    else:
        body.setdefault("unit_name", "ACME Trading")
        body.setdefault("items", [{"sku": "sku-1", "quantity_tins": 2, "tin_spec": 10}])
        body.setdefault("contact_person", "Lee")
        body.setdefault("contact_phone", "13800000000")

    repo = InMemoryAgentRunRepository()
    print_domain = Mock()
    print_domain.emit_job_submitted.return_value = bool(task.get("mock_publish_result", True))
    inventory_domain = Mock()
    inventory_domain.emit_stock_changed.return_value = bool(task.get("mock_publish_result", True))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "FHD_BUSINESS_API_KEY": "",
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.neuro_bus.domains.print_domain.get_print_domain", return_value=print_domain
                )
            )
            stack.enter_context(
                patch(
                    "app.neuro_bus.domains.inventory_domain.get_inventory_domain",
                    return_value=inventory_domain,
                )
            )
            publish = stack.enter_context(
                patch(
                    "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
                    return_value=bool(task.get("mock_publish_result", True)),
                )
            )
            response = client.post(
                path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(checks, "payload.event", payload.get("event"), expected.get("event"))
    _check_equal(checks, "payload.published", payload.get("published"), expected.get("published"))
    for name, actual in (
        ("error_code", payload.get("error_code")),
        ("publish_call_count", publish.call_count),
    ):
        _check_equal(checks, name, actual, expected.get(name), skip_when_expected_missing=True)
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "publish_call_count": publish.call_count,
            "run": run.to_dict() if run is not None else None,
            "print_call_count": print_domain.emit_job_submitted.call_count,
            "inventory_call_count": inventory_domain.emit_stock_changed.call_count,
        },
    )


def _run_system_maintenance_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.system_routes import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "set_default_printer").strip().lower()
    body = dict(task.get("body") or {})
    method = "POST"
    path = "/api/system/printer"
    if action == "set_default_printer":
        body.setdefault("printer_name", "HP")
    elif action == "enable_startup":
        path = "/api/system/startup"
    elif action == "disable_startup":
        method = "DELETE"
        path = "/api/system/startup"
    elif action == "backup_database":
        path = "/api/database/backup"
    elif action == "delete_database_backup":
        method = "DELETE"
        backup_file = str(body.get("backup_file") or "backup.sql")
        body["backup_file"] = backup_file
        path = f"/api/database/backup/{backup_file}"
    elif action == "restore_database":
        path = "/api/database/restore"
        body.setdefault("backup_file", "backup.sql")
    elif action == "clear_performance_cache":
        path = "/api/performance/cache/clear?pattern=test:*"
        body.setdefault("pattern", "test:*")
    elif action == "invalidate_performance_cache":
        path = "/api/performance/cache/invalidate"
        body.setdefault("keys", ["k1"])
    elif action == "reinitialize_performance":
        path = "/api/performance/optimize/reinitialize"

    repo = InMemoryAgentRunRepository()
    system_service = Mock()
    system_service.set_default_printer.return_value = {"success": True, "message": "ok"}
    system_service.enable_startup.return_value = {"success": True, "message": "enabled"}
    system_service.disable_startup.return_value = {"success": True, "message": "disabled"}
    database_service = Mock()
    database_service.backup_database.return_value = {
        "success": True,
        "message": "backed up",
        "backup_file": "backup.sql",
    }
    database_service.delete_backup.return_value = {
        "success": True,
        "message": "deleted",
        "backup_file": "backup.sql",
    }
    database_service.restore_database.return_value = {
        "success": True,
        "message": "restored",
        "backup_file": "backup.sql",
    }
    optimizer = Mock()
    optimizer.redis_cache.clear_pattern.return_value = 5
    optimizer.redis_cache.clear_local_cache.return_value = None
    optimizer.redis_cache.delete.return_value = 1
    optimizer.get_status.return_value = {"status": "ok"}
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(_authenticated_route_fixture(client, role_name="admin"))
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.facades.session_facade.get_system_service",
                    return_value=system_service,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.facades.session_facade.get_database_service",
                    return_value=database_service,
                )
            )
            stack.enter_context(
                patch(
                    "app.utils.performance.performance_initializer.get_performance_optimizer",
                    return_value=optimizer,
                )
            )
            stack.enter_context(
                patch(
                    "app.utils.performance.performance_initializer.init_performance_optimization",
                    return_value=optimizer,
                )
            )
            if method == "DELETE":
                response = client.delete(
                    path,
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )
            else:
                response = client.post(
                    path,
                    json=body,
                    headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
                )

    payload, run, checks = _route_agent_checks(response, expected, repo)
    if action in {"delete_database_backup", "restore_database", "reinitialize_performance"}:
        _check_equal(checks, "approval_required", payload.get("error_code"), "approval_required")
        _check_equal(
            checks,
            "no_effect_before_approval",
            database_service.mock_calls == [] and optimizer.mock_calls == [],
            True,
        )
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_dataset_rag_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.knowledge_v1 import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "query").strip().lower()
    body = dict(task.get("body") or {})
    method = "POST"
    path = "/api/knowledge/v1/datasets/platform-docs/query"
    if action == "query":
        body.setdefault("query", "Which model should AI routes use?")
        body.setdefault("tenant_id", "7")
        body.setdefault("include_answer", True)
    elif action == "ingest_document":
        path = "/api/knowledge/v1/datasets/platform-docs/documents"
        body.setdefault("source", "policy.pdf")
        body.setdefault("text", "AI routes should use AgentOrchestrator.")
        body.setdefault("tenant_id", "7")
    elif action == "diff_versions":
        path = "/api/knowledge/v1/datasets/platform-docs/versions/diff"
        body.setdefault("source", "policy.pdf")
        body.setdefault("tenant_id", "7")
        body.setdefault("from_version", "v1")
        body.setdefault("to_version", "latest")
    elif action == "rollback_version":
        path = "/api/knowledge/v1/datasets/platform-docs/versions/rollback"
        body.setdefault("source", "policy.pdf")
        body.setdefault("tenant_id", "7")
        body.setdefault("target_version", "v1")
    elif action == "rebuild_index":
        path = "/api/knowledge/v1/datasets/platform-docs/index/rebuild"
        body.setdefault("tenant_id", "7")
        body.setdefault("background", True)
    elif action == "cancel_rebuild":
        path = "/api/knowledge/v1/datasets/platform-docs/index/rebuild/rag_rebuild_1/cancel"
    elif action == "delete_document":
        method = "DELETE"
        path = "/api/knowledge/v1/datasets/platform-docs/documents/doc_1"

    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.answer.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "query": str(body.get("query") or ""),
        "answer": "AI routes should use AgentOrchestrator [1].",
        "chunks": [{"text": "AI routes should use AgentOrchestrator.", "source": "policy.pdf"}],
        "citations": [{"index": 1, "source": "policy.pdf"}],
    }
    service.ingest_document.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document": {"document_id": "doc_1", "source": "policy.pdf"},
        "chunk_count": 1,
    }
    service.diff_versions.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "source": "policy.pdf",
        "changed": True,
        "diff": ["--- v1", "+++ v2"],
    }
    service.rollback_document_version.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document": {"document_id": "doc_rollback"},
        "chunk_count": 1,
        "rolled_back_from": {"document_id": "doc_1", "version": 1},
    }
    service.start_rebuild_index.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "job": {"job_id": "rag_rebuild_1", "status": "queued"},
        "background": True,
    }
    service.cancel_rebuild_job.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "job_id": "rag_rebuild_1",
        "job": {"job_id": "rag_rebuild_1", "status": "cancelled"},
    }
    service.delete_document.return_value = {
        "success": True,
        "dataset_id": "platform-docs",
        "document_id": "doc_1",
        "deleted_chunks": 1,
    }
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        headers = {
            "X-Dataset-Tenant-ID": "7",
            "X-Dataset-Permissions": "dataset.read,dataset.write",
        }
        with ExitStack() as stack:
            stack.enter_context(_authenticated_route_fixture(client, role_name="admin"))
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                    return_value=service,
                )
            )
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_memory_v2_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.fastapi_routes.domains.misc.misc_routes import router
    from app.services import user_memory_service as memory_mod

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "propose_candidate").strip().lower()
    body = dict(task.get("body") or {})
    method = "POST"
    path = "/memory/v2/candidates"

    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        tmp_path = Path(tmp_dir)
        memory_dir = tmp_path / "memory"
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(tmp_path / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
            "XCAGI_USER_MEMORY_DIR": str(memory_dir),
            "XCAGI_USER_MEMORY_JSON_PATH": str(memory_dir / "memory_store.json"),
        }
        with ExitStack() as stack:
            user_id = str(stack.enter_context(_authenticated_route_fixture(client)))
            memory_owner = scoped_personal_memory_id({"actor_id": user_id, "tenant_id": "7"})
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(patch.object(memory_mod, "MEMORY_DIR", str(memory_dir)))
            stack.enter_context(
                patch.object(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
            )
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            memory_mod.reset_user_memory_service()
            try:
                if action == "propose_candidate":
                    body.setdefault("user_id", user_id)
                    body.setdefault("memory_type", "preference")
                    body.setdefault("key", "favorite_customer")
                    body.setdefault("value", "ACME Trading")
                    body.setdefault("source", "settings_ui")
                    body.setdefault("confidence", 0.9)
                else:
                    service = memory_mod.get_user_memory_service()
                    seed = service.propose_memory_candidate(
                        memory_owner,
                        "preference",
                        "favorite_customer",
                        "ACME Trading",
                        source="settings_ui",
                        confidence=0.9,
                    )
                    memory_id = str((seed.get("candidate") or {}).get("memory_id") or "")
                    if action in {"correct", "delete"}:
                        service.confirm_memory_candidate(memory_owner, memory_id)
                    body.setdefault("user_id", user_id)
                    if action == "confirm":
                        path = f"/memory/v2/{memory_id}/confirm"
                    elif action == "reject":
                        path = f"/memory/v2/{memory_id}/reject"
                        body.setdefault("reason", "not useful")
                    elif action == "correct":
                        method = "PATCH"
                        path = f"/memory/v2/{memory_id}"
                        body.setdefault("value", "ACME Trading Ltd.")
                        body.setdefault("reason", "user corrected value")
                    elif action == "delete":
                        method = "DELETE"
                        path = f"/memory/v2/{memory_id}"
                    else:
                        path = f"/memory/v2/{memory_id}/confirm"

                if method == "DELETE":
                    response = client.delete(
                        path,
                        params={
                            "user_id": user_id,
                            "reason": str(body.get("reason") or "user removed memory"),
                        },
                    )
                else:
                    response = client.request(method, path, json=body)
                # Read the real local authority before teardown, independently
                # of the service cache and the returned tool receipt.
                memory_snapshot = json.loads(memory_mod.configured_memory_path().read_text())
            finally:
                memory_mod.reset_user_memory_service()

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    memory_payload = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    candidate_payload = (
        payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    )
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "payload.memory_status",
        memory_payload.get("status") or candidate_payload.get("status"),
        expected.get("memory_status"),
        skip_when_expected_missing=True,
    )
    record = memory_payload or candidate_payload
    owned = memory_snapshot.get(memory_owner) or {}
    _check_equal(checks, "memory_authority.owners", sorted(memory_snapshot), [memory_owner])
    _check_equal(
        checks,
        "memory_authority.original_record",
        [
            item
            for item in owned.get("memory_v2_records", [])
            if item.get("memory_id") == record.get("memory_id")
        ],
        [record],
    )
    _check_equal(
        checks,
        "memory_authority.revision",
        record.get("revision"),
        expected.get("memory_revision"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "memory_authority.preference_projection",
        {
            key: item.get("value")
            for key, item in (owned.get("preferences") or {}).items()
            if item.get("memory_id") == record.get("memory_id")
        },
        {record["key"]: record.get("value")}
        if record.get("status") == "active" and record.get("memory_type") == "preference"
        else {},
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
        _check_equal(checks, "tool_attempts", [step.attempt_count for step in run.steps], [1])
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_materials_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import materials as materials_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-materials-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_material.return_value = {"success": True, "data": {"id": 1, "name": "树脂"}}
    service.update_material.return_value = {"success": True, "data": {"id": 1}}
    service.delete_material.return_value = None
    service.batch_delete_materials.return_value = None

    app = FastAPI()
    app.include_router(materials_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    method = "POST"
    path = "/api/materials"
    if action == "create":
        body.setdefault("name", "树脂")
        body.setdefault("material_code", "R-001")
    elif action == "update":
        method = "PUT"
        path = f"/api/materials/{int(task.get('material_id') or 1)}"
        body.setdefault("name", "树脂 v2")
    elif action == "delete":
        method = "DELETE"
        path = f"/api/materials/{int(task.get('material_id') or 1)}"
    elif action == "batch_delete":
        path = "/api/materials/batch-delete"
        body.setdefault("ids", [1, 2])
    else:
        return _failed(task, f"unsupported materials route action: {action}")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch.object(
                    materials_routes,
                    "get_material_application_service",
                    lambda: service,
                )
            )
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(
        checks,
        "payload.deleted_count",
        payload.get("deleted_count"),
        expected.get("deleted_count"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create": service.create_material.call_count,
                "update": service.update_material.call_count,
                "delete": service.delete_material.call_count,
                "batch_delete": service.batch_delete_materials.call_count,
            },
        },
    )


def _run_inventory_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import inventory as inventory_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "stock_in").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-inventory-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_storage_location.return_value = {"success": True, "id": 11}
    service.update_storage_location.return_value = {"success": True, "data": {"id": 11}}
    service.create_warehouse.return_value = {"success": True, "data": {"id": 1}}
    service.update_warehouse.return_value = {"success": True, "data": {"id": 1}}
    service.delete_warehouse.return_value = {"success": True}
    service.inventory_in.return_value = {"success": True, "data": {"transaction_type": "in"}}
    service.inventory_out.return_value = {"success": True, "data": {"transaction_type": "out"}}
    service.inventory_transfer.return_value = {
        "success": True,
        "data": {"transaction_type": "transfer"},
    }

    method = "POST"
    path = "/api/inventory/in"
    if action == "create_storage_location":
        path = "/api/inventory/locations"
        body.setdefault("code", "A-01")
    elif action == "update_storage_location":
        method = "PUT"
        path = f"/api/inventory/locations/{int(task.get('location_id') or 11)}"
        body.setdefault("status", "full")
    elif action == "create_warehouse":
        path = "/api/inventory/warehouses"
        body.setdefault("name", "主仓")
    elif action == "update_warehouse":
        method = "PUT"
        path = f"/api/inventory/warehouses/{int(task.get('warehouse_id') or 1)}"
        body.setdefault("name", "副仓")
    elif action == "delete_warehouse":
        method = "DELETE"
        path = f"/api/inventory/warehouses/{int(task.get('warehouse_id') or 1)}"
    elif action == "stock_in":
        path = "/api/inventory/in"
        body.setdefault("product_id", 1)
        body.setdefault("warehouse_id", 2)
        body.setdefault("quantity", 3)
    elif action == "stock_out":
        path = "/api/inventory/out"
        body.setdefault("product_id", 1)
        body.setdefault("warehouse_id", 2)
        body.setdefault("quantity", 1)
    elif action == "transfer":
        path = "/api/inventory/transfer"
        body.setdefault("product_id", 1)
        body.setdefault("from_warehouse_id", 1)
        body.setdefault("to_warehouse_id", 2)
        body.setdefault("quantity", 1)
    else:
        return _failed(task, f"unsupported inventory route action: {action}")

    app = FastAPI()
    app.include_router(inventory_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(
                _authenticated_route_fixture(
                    client,
                    permissions=[
                        f"tool.inventory.{action}",
                        "tool.inventory.query_transactions",
                    ],
                )
            )
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(inventory_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_storage_location": service.create_storage_location.call_count,
                "update_storage_location": service.update_storage_location.call_count,
                "create_warehouse": service.create_warehouse.call_count,
                "update_warehouse": service.update_warehouse.call_count,
                "delete_warehouse": service.delete_warehouse.call_count,
                "inventory_in": service.inventory_in.call_count,
                "inventory_out": service.inventory_out.call_count,
                "inventory_transfer": service.inventory_transfer.call_count,
            },
        },
    )


def _run_purchase_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from datetime import date

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.db.models import Product, PurchaseOrder, PurchaseOrderItem, Supplier, Warehouse
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.fastapi_routes import purchase as purchase_routes
    from app.infrastructure.tenant_scope import owned_tenant_scope

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create_order").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-purchase-user")
    repo = InMemoryAgentRunRepository()
    verifies_sql = action in {
        "create_order",
        "update_order",
        "approve_order",
        "cancel_order",
        "create_inbound",
    }
    service = Mock(wraps=PurchaseService()) if verifies_sql else Mock()
    service.create_supplier.return_value = {"success": True, "data": {"id": 7}}
    service.update_supplier.return_value = {"success": True, "data": {"id": 7}}
    service.delete_supplier.return_value = {"success": True}

    method = "POST"
    path = "/api/purchase/orders"
    if action == "create_supplier":
        path = "/api/purchase/suppliers"
        body.setdefault("name", "星光供应商")
    elif action == "update_supplier":
        method = "PUT"
        path = f"/api/purchase/suppliers/{int(task.get('supplier_id') or 7)}"
        body.setdefault("status", "active")
    elif action == "delete_supplier":
        method = "DELETE"
        path = f"/api/purchase/suppliers/{int(task.get('supplier_id') or 7)}"
    elif action == "create_order":
        path = "/api/purchase/orders"
        body.setdefault("supplier_id", 7)
        body.setdefault("warehouse_id", 1)
        body.setdefault("items", [{"product_id": 1, "quantity": 2, "unit_price": 10}])
    elif action == "update_order":
        method = "PUT"
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}"
        body.setdefault("remark", "调整交期")
    elif action == "approve_order":
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}/approve"
    elif action == "cancel_order":
        path = f"/api/purchase/orders/{int(task.get('order_id') or 9)}/cancel"
    elif action == "create_inbound":
        path = "/api/purchase/inbounds"
        body.setdefault("order_id", 9)
        body.setdefault("supplier_id", 7)
        body.setdefault("warehouse_id", 1)
        body.setdefault(
            "items", [{"order_item_id": 1, "product_id": 1, "quantity": 2, "unit_price": 10}]
        )
    else:
        return _failed(task, f"unsupported purchase route action: {action}")

    app = FastAPI()
    app.include_router(purchase_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "XCAGI_PRODUCT_SKU": "enterprise",
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                _authenticated_route_fixture(
                    client,
                    role_name="admin",
                    permissions=[
                        f"tool.purchase.{name}"
                        for name in (
                            "create_supplier",
                            "update_supplier",
                            "delete_supplier",
                            "create_order",
                            "update_order",
                            "approve_order",
                            "cancel_order",
                            "create_inbound",
                            "query_orders",
                            "query_inbounds",
                        )
                    ],
                )
            )
            if verifies_sql:
                with owned_tenant_scope(7), host_db.SessionLocal.begin() as db:
                    db.add(Supplier(id=7, code="eval-supplier", name="星光供应商", status="active"))
                    db.add(Product(id=1, name="资源物料"))
                    db.add(Warehouse(id=1, code="eval-warehouse", name="仓库"))
                    db.flush()
                    if action != "create_order":
                        db.add(
                            PurchaseOrder(
                                id=9,
                                order_no="eval-original-purchase",
                                supplier_id=7,
                                warehouse_id=1,
                                order_date=date.today(),
                                total_amount=100,
                                status="approved" if action == "create_inbound" else "draft",
                            )
                        )
                        db.flush()
                        db.add(
                            PurchaseOrderItem(
                                id=1,
                                order_id=9,
                                product_id=1,
                                quantity=10,
                                unit_price=10,
                                amount=100,
                                received_quantity=0,
                                status="pending",
                            )
                        )
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(purchase_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                params = {"approver": str(task.get("approver") or "manager")}
                if action == "approve_order":
                    response = client.post(path, params=params, headers=headers)
                else:
                    response = client.post(path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_supplier": service.create_supplier.call_count,
                "update_supplier": service.update_supplier.call_count,
                "delete_supplier": service.delete_supplier.call_count,
                "create_purchase_order": service.create_purchase_order.call_count,
                "update_purchase_order": service.update_purchase_order.call_count,
                "approve_purchase_order": service.approve_purchase_order.call_count,
                "cancel_purchase_order": service.cancel_purchase_order.call_count,
                "create_purchase_inbound": service.create_purchase_inbound.call_count,
            },
        },
    )


def _run_finance_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import finance as finance_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create_transaction").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-finance-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_transaction.return_value = {
        "success": True,
        "data": {"id": 31, "transaction_type": "expense"},
    }
    service.update_transaction.return_value = {"success": True, "data": {"id": 31}}
    service.delete_transaction.return_value = {"success": True, "message": "凭证已删除"}

    method = "POST"
    path = "/api/finance/transactions"
    if action == "create_transaction":
        path = "/api/finance/transactions"
        body.setdefault("transaction_type", "expense")
        body.setdefault("amount", 128.5)
    elif action == "update_transaction":
        method = "PUT"
        path = f"/api/finance/transactions/{int(task.get('transaction_id') or 31)}"
        body.setdefault("status", "paid")
    elif action == "delete_transaction":
        method = "DELETE"
        path = f"/api/finance/transactions/{int(task.get('transaction_id') or 31)}"
    else:
        return _failed(task, f"unsupported finance route action: {action}")

    app = FastAPI()
    app.include_router(finance_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(finance_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_transaction": service.create_transaction.call_count,
                "update_transaction": service.update_transaction.call_count,
                "delete_transaction": service.delete_transaction.call_count,
            },
        },
    )


def _run_products_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.product import routes as product_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "batch_create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-products-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.batch_add_products.return_value = {"success": True, "data": {"success_count": 1}}
    service.update_product.return_value = {"success": True, "data": {"id": 7}}
    service.delete_product.return_value = {"success": True, "message": "产品删除成功"}

    method = "POST"
    path = "/api/products/batch"
    if action == "batch_create":
        path = "/api/products/batch"
        body.setdefault("products", [{"name": "5003", "unit_price": 12.5}])
    elif action == "update":
        method = "PUT"
        path = f"/api/products/{int(task.get('product_id') or 7)}"
        body.setdefault("name", "5003 v2")
    elif action == "delete":
        method = "DELETE"
        path = f"/api/products/{int(task.get('product_id') or 7)}"
    else:
        return _failed(task, f"unsupported products route action: {action}")

    app = FastAPI()
    app.include_router(product_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(product_routes, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.delete(path, headers=headers)
            elif method == "PUT":
                response = client.put(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "batch_add_products": service.batch_add_products.call_count,
                "update_product": service.update_product.call_count,
                "delete_product": service.delete_product.call_count,
            },
        },
    )


def _run_products_compat_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.application.excel_imports as excel_imports
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.legacy.routes.product import compat_routes as product_compat_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-products-compat-user")
    repo = InMemoryAgentRunRepository()

    path = "/products/add"
    if action == "create":
        path = "/products/add"
        body.setdefault("product_name", "5003")
        body.setdefault("unit", "个")
    elif action == "update":
        path = "/products/update"
        body.setdefault("id", 7)
        body.setdefault("name", "5003 v2")
    elif action == "delete":
        path = "/products/delete"
        body.setdefault("id", 7)
    elif action == "batch_delete":
        path = "/products/batch-delete"
        body.setdefault("ids", [7, 8])
    else:
        return _failed(task, f"unsupported products compat route action: {action}")

    app = FastAPI()
    app.include_router(product_compat_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        excel_imports.__dict__["_parse_price"] = lambda value: 0.0
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
                stack.enter_context(
                    patch(
                        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                        return_value=repo,
                    )
                )
                stack.enter_context(
                    patch(
                        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                        return_value=False,
                    )
                )
                stack.enter_context(
                    patch("app.legacy.routes.product.compat_routes._products_write_raise")
                )
                stack.enter_context(
                    patch(
                        "app.legacy.routes.product.compat_routes._business_mod_json_block",
                        return_value=None,
                    )
                )
                insert_row = stack.enter_context(
                    patch(
                        "app.legacy.routes.product.compat_routes.products_pg_insert_row",
                        return_value=7,
                    )
                )
                update_row = stack.enter_context(
                    patch("app.legacy.routes.product.compat_routes.products_pg_update_row")
                )
                delete_row = stack.enter_context(
                    patch("app.legacy.routes.product.compat_routes.products_pg_delete_row")
                )
                batch_delete_rows = stack.enter_context(
                    patch(
                        "app.legacy.routes.product.compat_routes.products_pg_batch_delete_rows",
                        return_value=(2, []),
                    )
                )
                response = client.post(path, json=body, headers={"X-User-Id": user_id})
        finally:
            excel_imports.__dict__.pop("_parse_price", None)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "insert_row": insert_row.call_count,
                "update_row": update_row.call_count,
                "delete_row": delete_row.call_count,
                "batch_delete_rows": batch_delete_rows.call_count,
            },
        },
    )


def _run_customers_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.application.customer_app_service import CustomerApplicationService
    from app.db.models.purchase_unit import PurchaseUnit
    from app.fastapi_routes.domains.customer import routes as customer_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-customers-user")
    repo = InMemoryAgentRunRepository()
    service = Mock(wraps=CustomerApplicationService())
    deleted_ids: list[int] = []
    method = "POST"
    path = "/customers"
    if action in {"create", "update"}:
        body.setdefault("unit_name", "星光贸易")
        body.setdefault("contact_person", "张三")
        body.setdefault("contact_phone", "13900000000")
        body.setdefault("contact_address", "上海")
        if action == "update":
            method = "PUT"
            path = f"/customers/{int(task.get('customer_id') or 7)}"
    elif action == "delete":
        method = "DELETE"
        path = f"/customers/{int(task.get('customer_id') or 7)}"
    elif action == "batch_delete":
        path = "/customers/batch-delete"
        body.setdefault("ids", [7, 8])
    else:
        return _failed(task, f"unsupported customers route action: {action}")

    app = FastAPI()
    app.include_router(customer_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir, ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
                    "MODEL_USAGE_WALLET_BACKEND": "audit",
                    "MODEL_USAGE_WALLET_REQUIRED": "",
                    "XCAGI_PRODUCT_SKU": "enterprise",
                },
                clear=False,
            )
        )
        stack.enter_context(_authenticated_route_fixture(client, role_name="admin"))
        customer_sessions = host_db.SessionLocal
        engine = customer_sessions.kw["bind"]
        if action != "create":
            with customer_sessions.begin() as db:
                db.add_all(
                    PurchaseUnit(id=value, tenant_id=7, unit_name=f"Customer {value}")
                    for value in (7, 8)
                )
        stack.enter_context(
            patch("app.application.customer_app_service.get_customers_session", customer_sessions)
        )
        stack.enter_context(
            patch(
                "app.infrastructure.persistence.compat_db.compat_db_base.get_sync_engine",
                return_value=engine,
            )
        )
        stack.enter_context(patch("app.application.get_customer_app_service", return_value=service))
        stack.enter_context(
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            )
        )
        stack.enter_context(
            patch(
                "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
                return_value=False,
            )
        )
        headers = {"X-User-Id": user_id}
        if method == "DELETE":
            response = client.delete(path, headers=headers)
        elif method == "PUT":
            response = client.put(path, json=body, headers=headers)
        else:
            response = client.post(path, json=body, headers=headers)
        if action in {"delete", "batch_delete"}:
            with customer_sessions() as db:
                remaining_ids = {
                    row[0]
                    for row in db.connection().exec_driver_sql("SELECT id FROM purchase_units")
                }
            deleted_ids = sorted({7, 8} - remaining_ids)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    if action in {"delete", "batch_delete"}:
        _check_equal(
            checks, "deleted_customer_ids", deleted_ids, expected.get("deleted_customer_ids", [])
        )
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create": service.create.call_count,
                "update": service.update.call_count,
                "batch_delete": service.batch_delete.call_count,
                "deleted_customer_rows": len(deleted_ids),
            },
        },
    )


def _route_agent_checks(response, expected, repo):
    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
        _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return payload, run, checks


def _run_shipment_records_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.db.models.shipment import ShipmentRecord
    from app.fastapi_routes import shipment_orders
    from app.infrastructure.tenant_scope import tenant_scope

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-shipment-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    service.create_shipment.return_value = {"success": True, "data": {"id": 7}}
    service.update_shipment_record.return_value = {"success": True, "data": {"id": 7}}
    service.delete_shipment_record.return_value = {"success": True, "deleted_count": 1}
    authority_before = []
    authority_after = []

    method = "POST"
    path = "/api/shipment/shipment-records/record"
    if action == "update":
        method = "PATCH"
        body.setdefault("id", int(task.get("record_id") or 7))
        body.setdefault("status", "printed")
    elif action == "delete":
        method = "DELETE"
        body.setdefault("id", int(task.get("record_id") or 7))
    elif action != "create":
        return _failed(task, f"unsupported shipment records route action: {action}")

    app = FastAPI()
    app.include_router(shipment_orders.router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(_authenticated_route_fixture(client))
            if action in {"update", "delete"}:
                # Seed the real target so an inert mock cannot accidentally
                # satisfy a delete postcondition merely because the DB is empty.
                with tenant_scope(7), host_db.SessionLocal.begin() as db:
                    db.add(
                        ShipmentRecord(
                            id=body["id"],
                            tenant_id=7,
                            purchase_unit="Fixture customer",
                            product_name="Unchanged product",
                            quantity_kg=3,
                            quantity_tins=1,
                            status="pending",
                        )
                    )
                with host_db.SessionLocal() as db:
                    authority_before = [
                        list(row)
                        for row in db.connection().exec_driver_sql(
                            "SELECT id, tenant_id, product_name, status FROM shipment_records"
                        )
                    ]
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(shipment_orders, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            if method == "DELETE":
                response = client.request("DELETE", path, json=body, headers=headers)
            elif method == "PATCH":
                response = client.patch(path, json=body, headers=headers)
            else:
                response = client.post(path, json=body, headers=headers)
            if action in {"update", "delete"}:
                with host_db.SessionLocal() as db:
                    authority_after = [
                        list(row)
                        for row in db.connection().exec_driver_sql(
                            "SELECT id, tenant_id, product_name, status FROM shipment_records"
                        )
                    ]

    payload, run, checks = _route_agent_checks(response, expected, repo)
    if action in {"update", "delete"}:
        _check_equal(
            checks, "authoritative_mock_write_unchanged", authority_after, authority_before
        )
    return _result(
        task,
        checks,
        {
            "response": payload,
            "authority_before": authority_before,
            "authority_after": authority_after,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "create_shipment": service.create_shipment.call_count,
                "update_shipment_record": service.update_shipment_record.call_count,
                "delete_shipment_record": service.delete_shipment_record.call_count,
            },
        },
    )


def _run_shipment_orders_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import shipment_orders

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "generate").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-shipment-order-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()

    method = "POST"
    path = "/api/shipment/generate"
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        from app.utils.path_io.path_utils import get_shipment_output_dir

        with patch.dict(os.environ, {"XCAGI_DATA_DIR": tmp_dir}):
            shipment_output_dir = Path(get_shipment_output_dir())
        shipment_output_dir.mkdir(parents=True)
        shipment_file = shipment_output_dir / "shipment.xlsx"
        shipment_file.write_bytes(b"fake")
        service.generate_shipment_document.return_value = {
            "success": True,
            "file_path": str(shipment_file),
            "record_id": 7,
        }
        service.mark_as_printed.return_value = {"success": True, "message": "已标记为已打印"}
        service.clear_shipment_by_unit.return_value = {"success": True, "cleared_count": 2}
        service.set_order_sequence.return_value = {"success": True, "sequence": 12}
        service.reset_order_sequence.return_value = {"success": True, "sequence": 1}
        service.clear_all_orders.return_value = {"success": True, "deleted_count": 5}
        service.delete_shipment.return_value = {"success": True}

        if action == "generate":
            path = "/api/shipment/generate"
            body.setdefault("unit_name", "星光贸易")
            body.setdefault("products", [{"name": "5003", "qty": 2}])
        elif action == "generate_batch":
            path = "/api/shipment/generate-batch"
            body.setdefault(
                "shipments",
                [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}],
            )
        elif action == "print":
            path = "/api/shipment/print"
            body.setdefault("file_path", str(shipment_file))
            body.setdefault("order_id", 7)
            body.setdefault("printer_name", "HP")
        elif action == "clear_shipment":
            path = str(task.get("route_path") or "/api/shipment/orders/clear-shipment")
            body.setdefault("purchase_unit", "星光贸易")
        elif action == "set_sequence":
            path = str(task.get("route_path") or "/api/orders/set-sequence")
            body.setdefault("sequence", 12)
        elif action == "reset_sequence":
            path = str(task.get("route_path") or "/api/shipment/orders/reset-sequence")
        elif action == "clear_all":
            method = "DELETE"
            path = str(task.get("route_path") or "/api/orders/clear-all")
        elif action == "delete":
            method = "DELETE"
            path = str(task.get("route_path") or "/api/shipment/orders/7")
        else:
            return _failed(task, f"unsupported shipment orders route action: {action}")

        app = FastAPI()
        app.include_router(shipment_orders.router)
        client = TestClient(app, raise_server_exceptions=False)

        env_patch = {
            "XCAGI_DATA_DIR": str(Path(tmp_dir)),
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            # Preserve this legacy fixture's original tenantless local-account scope.
            # Enterprise tenant requests are separately asserted to fail closed.
            stack.enter_context(_authenticated_route_fixture(client, tenant_id=None))
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(shipment_orders, "_svc", lambda: service))
            headers = {"X-User-Id": user_id}
            response = client.request(method, path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "generate_shipment_document": service.generate_shipment_document.call_count,
                "mark_as_printed": service.mark_as_printed.call_count,
                "clear_shipment_by_unit": service.clear_shipment_by_unit.call_count,
                "set_order_sequence": service.set_order_sequence.call_count,
                "reset_order_sequence": service.reset_order_sequence.call_count,
                "clear_all_orders": service.clear_all_orders.call_count,
                "delete_shipment": service.delete_shipment.call_count,
            },
        },
    )


def _run_print_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes import print_routes

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "print_document").strip().lower()
    body = dict(task.get("body") or {})
    user_id = str(task.get("user_id") or "eval-print-user")
    repo = InMemoryAgentRunRepository()
    service = Mock()
    method = "POST"
    path = "/api/print/document"

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        document_file = Path(tmp_dir) / "document.pdf"
        document_file.write_bytes(b"%PDF")
        label_file = Path(tmp_dir) / "label.png"
        label_file.write_bytes(b"\x89PNG\r\n")
        service.get_printers.return_value = {
            "success": True,
            "printers": [{"name": "DocPrinter"}, {"name": "LabelPrinter"}],
        }
        service.save_printer_selection.return_value = {
            "success": True,
            "message": "打印机选择已保存",
        }
        service.classify_printers.return_value = {
            "document": ["DocPrinter"],
            "label": ["LabelPrinter"],
        }
        service.print_document.return_value = {"success": True, "message": "文档已提交打印"}
        service.print_label.return_value = {"success": True, "message": "标签已打印"}
        service.test_printer.return_value = {"success": True, "message": "测试页已发送"}
        print_app = Mock()
        print_app.print_single_label.return_value = {
            "success": True,
            "message": "标签已打印",
            "model_number": "M-1",
            "quantity": 2,
        }
        product_service = Mock()
        product_service.search_products.return_value = [
            {"name": "产品M1", "specification": "红色", "unit": "盒"}
        ]

        if action == "save_printer_selection":
            method = "PUT"
            path = "/api/print/printer-selection"
            body.setdefault("document_printer", "DocPrinter")
            body.setdefault("label_printer", "LabelPrinter")
        elif action == "print_document":
            path = "/api/print/document"
            body.setdefault("file_path", str(document_file))
            body.setdefault("printer_name", "DocPrinter")
            body.setdefault("use_automation", False)
        elif action == "print_label":
            path = "/api/print/label"
            body.setdefault("file_path", str(label_file))
            body.setdefault("printer_name", "LabelPrinter")
            body.setdefault("copies", 2)
            body.setdefault("require_confirm", False)
        elif action == "test":
            path = "/api/print/test"
            body.setdefault("printer_name", "DocPrinter")
        elif action == "workflow_label_dispatch":
            path = "/api/print/workflow/label-print/dispatch"
            body.setdefault("model_number", "M-1")
            body.setdefault("quantity", 2)
            body.setdefault("idempotency_key", "idem-eval")
        else:
            return _failed(task, f"unsupported print route action: {action}")

        app = FastAPI()
        app.include_router(print_routes.router)
        client = TestClient(app, raise_server_exceptions=False)

        env_patch = {
            "XCAGI_PRINT_ALLOWED_ROOTS": str(Path(tmp_dir)),
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(patch.object(print_routes, "_svc", lambda: service))
            stack.enter_context(
                patch(
                    "app.application.print_app_service.get_print_application_service",
                    return_value=print_app,
                )
            )
            stack.enter_context(
                patch("app.application.get_product_app_service", return_value=product_service)
            )
            headers = {"X-User-Id": user_id}
            response = client.request(method, path, json=body, headers=headers)

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "service_calls": {
                "get_printers": service.get_printers.call_count,
                "save_printer_selection": service.save_printer_selection.call_count,
                "print_document": service.print_document.call_count,
                "print_label": service.print_label.call_count,
                "test_printer": service.test_printer.call_count,
                "print_single_label": print_app.print_single_label.call_count,
                "product_search": product_service.search_products.call_count,
            },
        },
    )


def _run_tools_execute_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.system_routes import router
    from app.fastapi_routes.tools_execute import router as tools_execute_router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = bool(task.get("mock_publish_result", True))
    app = FastAPI()
    app.include_router(router)
    # tools/execute 已从 system routes 拆出；eval 需单独挂载 always-on 路由。
    app.include_router(tools_execute_router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(_authenticated_route_fixture(client))
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain)
            )
            response = client.post(
                str(task.get("path") or "/api/tools/execute"),
                json=dict(
                    task.get("body")
                    or {
                        "tool_id": "ocr",
                        "action": "request",
                        "params": {
                            "request_id": "tools-ocr-eval",
                            "image_url": "https://example.invalid/label.png",
                            "ocr_type": "invoice",
                            "user_id": str(task.get("user_id") or "eval-user"),
                        },
                    }
                ),
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
            "publish_call_count": ocr_domain.emit_ocr_requested.call_count,
        },
    )


def _run_templates_analyze_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.system_routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    filename = str(task.get("filename") or "shipment-template.xlsx")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with ExitStack() as stack:
            stack.enter_context(_authenticated_route_fixture(client))
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_structured_excel_preview",
                    return_value=dict(
                        task.get("mock_structured_result")
                        or {
                            "fields": [{"label": "客户", "type": "dynamic"}],
                            "sample_rows": [{"客户": "ACME Trading"}],
                        }
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_grid_preview",
                    return_value=dict(
                        task.get("mock_grid_preview") or {"rows": [["客户"], ["ACME Trading"]]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_grid_style_cache",
                    return_value=dict(task.get("mock_style_cache") or {"cells": {}}),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._extract_excel_all_sheets_preview",
                    return_value=list(task.get("mock_sheets") or [{"sheet_name": "出货"}]),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.document_templates_service._list_excel_sheet_names",
                    return_value=list(task.get("mock_sheet_names") or ["出货"]),
                )
            )
            response = client.post(
                "/api/templates/analyze",
                files={
                    "file": (
                        filename,
                        bytes(str(task.get("file_body") or "eval-template"), "utf-8"),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data=dict(
                    task.get("form") or {"template_name": "发货模板", "template_scope": "shipment"}
                ),
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks,
            "artifact_count",
            len(run.artifacts),
            expected.get("artifact_count"),
            skip_when_expected_missing=True,
        )
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_excel_skill_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openpyxl import Workbook

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.excel.excel_routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    route_path = str(task.get("path") or "/api/skills/analyze/excel")

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        xlsx_path = Path(tmp_dir) / str(task.get("filename") or "excel-skill-route.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = str(task.get("sheet_name") or "Sheet1")
        ws.append(["客户", "数量"])
        ws.append(["ACME Trading", 3])
        wb.save(xlsx_path)

        body = dict(task.get("body") or {})
        body.setdefault("file_path", str(xlsx_path))
        body.setdefault("sheet_name", ws.title)

        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        with (
            patch.dict(os.environ, env_patch, clear=False),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            response = client.post(
                route_path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_label_template_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.excel.excel_routes import router

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        body = dict(
            task.get("body")
            or {
                "image_path": "/tmp/label.png",
                "class_name": "ProductLabelTemplate",
                "enable_ocr": True,
            }
        )
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
            stack.enter_context(
                patch(
                    "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                    return_value=repo,
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.analyze_image",
                    return_value=dict(
                        task.get("mock_analysis")
                        or {"success": True, "file": "label.png", "size": [800, 600]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
                    return_value=dict(
                        task.get("mock_ocr_result")
                        or {"success": True, "fields": [{"label": "品名", "value": "清漆"}]}
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
                    return_value=str(
                        task.get("mock_code") or "class ProductLabelTemplate:\n    pass\n"
                    ),
                )
            )
            response = client.post(
                "/api/skills/generate-label-template",
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload = response.json()
    run = repo.get(str(payload.get("run_id") or payload.get("agent_run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "status_code", response.status_code, expected.get("status_code"))
    _check_equal(checks, "payload.success", payload.get("success"), expected.get("success"))
    _check_equal(
        checks, "payload.agent_status", payload.get("agent_status"), expected.get("agent_status")
    )
    _check_equal(
        checks,
        "payload.run_id_present",
        bool(payload.get("run_id") and payload.get("agent_run_id")),
        expected.get("run_id_present"),
        skip_when_expected_missing=True,
    )
    _check_equal(checks, "run_attached", run is not None, True)
    if run is not None:
        _check_equal(checks, "run.status", run.status, expected.get("run_status"))
        _check_equal(checks, "run.intent", run.intent, expected.get("intent"))
        _check_equal(
            checks, "tool_call_count", len(run.tool_calls), expected.get("tool_call_count")
        )
        _check_tool_calls(checks, run.tool_calls, list(expected.get("tool_calls") or []))
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _run_document_template_route_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.fastapi_routes.domains.system.system_routes import router

    expected = dict(task.get("expected") or {})
    action = str(task.get("route_action") or "create").strip().lower() or "create"
    if action == "update":
        path = "/api/templates/update"
    elif action == "delete":
        path = "/api/templates/delete"
    else:
        path = "/api/templates/create"
    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
        env_patch = {
            "MODEL_USAGE_LEDGER_PATH": str(Path(tmp_dir) / "usage.json"),
            "MODEL_USAGE_WALLET_BACKEND": "audit",
            "MODEL_USAGE_WALLET_REQUIRED": "",
        }
        body = dict(task.get("body") or {})
        if action == "update":
            body.setdefault("id", "db:1")
            body.setdefault("name", "发货模板 v2")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板更新成功",
                    "template": {"id": "db:1", "db_id": 1, "name": body.get("name")},
                }
            )
            patch_target = "app.legacy.routes.document_templates_compat.run_archive_template_update"
        elif action == "delete":
            body.setdefault("id", "db:1")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板删除成功",
                    "deleted": {"id": body.get("id"), "db_id": 1},
                }
            )
            patch_target = "app.legacy.routes.document_templates_compat.run_archive_template_delete"
        else:
            body.setdefault("name", "发货模板")
            body.setdefault("template_type", "Excel")
            mocked_response = dict(
                task.get("mock_response")
                or {
                    "success": True,
                    "message": "模板创建成功",
                    "template": {"id": "db:1", "db_id": 1, "name": body.get("name")},
                }
            )
            patch_target = "app.legacy.routes.document_templates_compat.run_archive_template_create"
        mocked_status = int(task.get("mock_status_code") or 200)
        with (
            _authenticated_route_fixture(client),
            patch.dict(os.environ, env_patch, clear=False),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
            patch(patch_target, return_value=(mocked_response, mocked_status)),
        ):
            response = client.post(
                path,
                json=body,
                headers={"X-User-Id": str(task.get("user_id") or "eval-user")},
            )

    payload, run, checks = _route_agent_checks(response, expected, repo)
    return _result(
        task,
        checks,
        {
            "response": payload,
            "run": run.to_dict() if run is not None else None,
        },
    )


def _inject_file_analysis_path(payload: dict[str, Any], file_path: Path, source: str) -> None:
    data = payload.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        payload["data"] = data
    analysis = data.setdefault("file_analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}
        data["file_analysis"] = analysis
    analysis["file_path"] = str(file_path)
    analysis.setdefault("saved_name", source)
    analysis.setdefault("filename", source)


def _run_agent_run_memory_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    expected = dict(task.get("expected") or {})
    repo = InMemoryAgentRunRepository()
    payload = dict(task.get("payload") or {})
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        result = attach_chat_trace_run(
            payload,
            message=str(task.get("message") or task.get("id") or ""),
            runtime_context={"source": "agent_eval", "task_id": str(task.get("id") or "")},
            user_id="eval-user",
            source="agent_eval",
            channel="eval_chat",
        )

    run = repo.get(str(result.get("run_id") or ""))
    checks: list[dict[str, Any]] = []
    _check_equal(checks, "run_attached", run is not None, True)
    if run is None:
        return _result(task, checks, {"payload": result})

    _check_equal(
        checks,
        "memory_reference_count",
        len(run.memory_references),
        expected.get("memory_reference_count"),
    )
    _check_equal(
        checks,
        "memory_hit_count",
        run.metadata.get("memory_hit_count"),
        expected.get("memory_hit_count"),
    )
    if run.memory_references:
        reference = run.memory_references[0]
        for key in ("query", "memory_type", "source", "status"):
            if key in expected:
                _check_equal(
                    checks,
                    f"memory_references[0].{key}",
                    getattr(reference, key),
                    expected.get(key),
                )
        if "first_hit_chunk_id" in expected:
            first_chunk_id = str(
                (reference.hits[0] if reference.hits else {}).get("chunk_id") or ""
            )
            _check_equal(
                checks,
                "memory_references[0].hits[0].chunk_id",
                first_chunk_id,
                expected.get("first_hit_chunk_id"),
            )
    _check_event_types(checks, run.events, list(expected.get("event_types") or []))
    return _result(task, checks, {"run": run.to_dict(), "payload": result})


def _run_memory_v2_lifecycle_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.domain.shared_services.user_memory_service import (
        UserMemoryService,
        reset_user_memory_service,
    )
    from app.services import user_memory_service as memory_module

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    user_id = str(task.get("user_id") or "eval-user")
    key = str(task.get("key") or "favorite_customer")
    value = task.get("value")
    corrected_value = task.get("corrected_value", value)
    entity_key = str(task.get("entity_key") or "customer_alias:acme")
    entity_value = task.get("entity_value", corrected_value)

    with tempfile.TemporaryDirectory() as tmp_dir:
        memory_path = Path(tmp_dir) / "memory_store.json"
        with (
            patch.object(memory_module, "MEMORY_DIR", tmp_dir),
            patch.object(memory_module, "JSON_MEMORY_PATH", str(memory_path)),
        ):
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None
            svc = UserMemoryService(storage_type="json")

            proposed = svc.propose_memory_candidate(
                user_id,
                "preference",
                key,
                value,
                confidence=float(task.get("confidence") or 0.8),
                evidence=[{"source": "agent_eval"}],
            )
            duplicate = svc.propose_memory_candidate(user_id, "preference", key, value)
            preference_before = svc.get_preference(user_id, key)
            candidate = dict(proposed.get("candidate") or {})
            confirmed = svc.confirm_memory_candidate(user_id, str(candidate.get("memory_id") or ""))
            corrected = svc.correct_memory(
                user_id,
                str(candidate.get("memory_id") or ""),
                value=corrected_value,
                reason="eval correction",
            )

            entity = svc.propose_memory_candidate(user_id, "entity", entity_key, entity_value)
            entity_candidate = dict(entity.get("candidate") or {})
            svc.confirm_memory_candidate(user_id, str(entity_candidate.get("memory_id") or ""))
            deleted = svc.delete_memory(
                user_id,
                str(entity_candidate.get("memory_id") or ""),
                reason="eval cleanup",
            )

            summary = svc.get_memory_v2_summary(user_id)
            memory_summary = svc.get_memory_summary(user_id)
            active_records = svc.list_memories(user_id, status="active")
            deleted_records = svc.list_memories(user_id, status="deleted")
            preference_after_correct = svc.get_preference(user_id, key)
            persisted = memory_path.exists()

            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None

    _check_equal(checks, "candidate_created", proposed.get("created"), True)
    _check_equal(checks, "duplicate_created", duplicate.get("created"), False)
    _check_equal(checks, "preference_before_confirmation", preference_before, None)
    _check_equal(
        checks,
        "confirmed_status",
        dict(confirmed.get("memory") or {}).get("status"),
        "active",
    )
    _check_equal(
        checks,
        "corrected_value",
        dict(corrected.get("memory") or {}).get("value"),
        corrected_value,
    )
    _check_equal(checks, "preference_after_correct", preference_after_correct, corrected_value)
    _check_equal(
        checks, "deleted_status", dict(deleted.get("memory") or {}).get("status"), "deleted"
    )
    _check_equal(checks, "summary.total", summary.get("total"), expected.get("total"))
    _check_equal(
        checks,
        "summary.by_status.active",
        dict(summary.get("by_status") or {}).get("active"),
        expected.get("active_count"),
    )
    _check_equal(
        checks,
        "summary.by_status.deleted",
        dict(summary.get("by_status") or {}).get("deleted"),
        expected.get("deleted_count"),
    )
    _check_equal(
        checks,
        "summary.by_type.preference",
        dict(summary.get("by_type") or {}).get("preference"),
        expected.get("preference_count"),
    )
    _check_equal(
        checks,
        "summary.by_type.entity",
        dict(summary.get("by_type") or {}).get("entity"),
        expected.get("entity_count"),
    )
    _check_equal(
        checks,
        "memory_summary.memory_v2_active_count",
        memory_summary.get("memory_v2_active_count"),
        expected.get("active_count"),
    )
    _check_equal(checks, "active_records", len(active_records), expected.get("active_count"))
    _check_equal(checks, "deleted_records", len(deleted_records), expected.get("deleted_count"))
    _check_equal(checks, "persisted", persisted, True)
    return _result(
        task,
        checks,
        {
            "proposed": proposed,
            "duplicate": duplicate,
            "confirmed": confirmed,
            "corrected": corrected,
            "deleted": deleted,
            "summary": summary,
            "memory_summary": memory_summary,
        },
    )


def _run_memory_v2_planner_context_task(task: dict[str, Any]) -> dict[str, Any]:
    """The legacy catalog name now exercises the unique Codex goal/context entry."""
    from starlette.requests import Request

    from app.application.agent_task_context import scoped_personal_memory_id
    from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal

    try:
        from evals.owned_attachment_eval import codex_eval_runtime
    except ModuleNotFoundError:
        from owned_attachment_eval import codex_eval_runtime

    client = SimpleNamespace(headers={})
    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as root, ExitStack() as stack:
        stack.enter_context(_authenticated_route_fixture(client))
        stack.enter_context(patch.object(UserMemoryService, "_instance", None))
        stack.enter_context(patch.object(UserMemoryStore, "_instance", None))
        stack.enter_context(patch.dict(os.environ, {"XCAGI_LONG_TERM_MEMORY_BACKEND": "legacy"}))
        from app.application.user_memory_vector_app_service import (
            UserMemoryRagApplicationService,
            UserMemoryVectorIngestApplicationService,
        )
        from app.infrastructure.persistence.user_memory_vector_store import (
            SQLiteUserMemoryVectorStore,
        )

        vector_store = SQLiteUserMemoryVectorStore(str(Path(root) / "memory.sqlite"))
        rag = UserMemoryRagApplicationService(vector_store=vector_store)
        ingest = UserMemoryVectorIngestApplicationService(vector_store=vector_store)
        stack.enter_context(
            patch(
                "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
                return_value=rag,
            )
        )
        stack.enter_context(
            patch(
                "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
                return_value=ingest,
            )
        )
        memory_service = UserMemoryService(storage_type="memory")
        stack.enter_context(
            patch(
                "app.domain.shared_services.user_memory_service.get_user_memory_service",
                return_value=memory_service,
            )
        )
        recalled = stack.enter_context(
            patch.object(
                memory_service,
                "format_memory_v2_for_prompt",
                wraps=memory_service.format_memory_v2_for_prompt,
            )
        )
        runtime = codex_eval_runtime(stack, Path(root), client, task)
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        context = authenticated_runtime_context(
            {"conversation_id": str(task.get("user_id") or "eval-memory-user")}, principal
        )
        namespace = scoped_personal_memory_id(context)
        active = memory_service.propose_memory_candidate(
            namespace,
            "preference",
            "favorite_customer",
            "ACME Trading",
            source="agent_eval",
            confidence=0.9,
        )
        assert memory_service.confirm_memory_candidate(namespace, active["candidate"]["memory_id"])[
            "success"
        ]
        memory_service.propose_memory_candidate(
            namespace, "preference", "pending_customer", "PENDING LTD"
        )
        foreign = memory_service.propose_memory_candidate(
            "foreign-owner", "preference", "foreign_customer", "FOREIGN LTD"
        )
        assert memory_service.confirm_memory_candidate(
            "foreign-owner", foreign["candidate"]["memory_id"]
        )["success"]
        run = runtime.start(context)
        evidence = (
            run.metadata.get("runtime_goal_contract", {})
            .get("request", {})
            .get("context_evidence", [])
        )
        memory = next((row for row in evidence if row.get("source") == "memory_v2"), {})
        summary = str(memory.get("summary") or "")
        _check_equal(checks, "host_recalled_scoped_memory_once", recalled.call_count, 1)
        _check_equal(
            checks,
            "host_recalled_scope",
            recalled.call_args.kwargs if recalled.call_args else {},
            {"user_id": namespace, "max_items": 6},
        )
        _check_equal(
            checks,
            "foreign_memory_absent",
            "FOREIGN LTD" in json.dumps(evidence, ensure_ascii=False),
            False,
        )
        _check_equal(checks, "memory_owner", memory.get("owner_id"), namespace)
        _check_equal(checks, "context_has_memory_v2", bool(summary), True)
        _check_equal(
            checks,
            "same_context_reaches_codex",
            bool(
                runtime.inputs
                and json.dumps(summary, ensure_ascii=False)[1:-1] in runtime.inputs[0]
            ),
            True,
        )
        _check_equal(checks, "original_goal_verified", run.status, "completed")
        _check_equal(checks, "runtime", run.metadata.get("runtime_type"), "codex")
        for key, present in (("summary_contains", True), ("summary_not_contains", False)):
            if expected.get(key):
                fragment = str(expected[key])
                _check_equal(checks, key, fragment in summary, present)
        return _result(task, checks, {"run": run.to_dict(), "context_evidence": evidence})
