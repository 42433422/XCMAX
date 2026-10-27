def _run_memory_v2_governance_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.domain.shared_services.user_memory_service import (
        UserMemoryService,
        reset_user_memory_service,
    )
    from app.services import user_memory_service as memory_module

    expected = dict(task.get("expected") or {})
    checks: list[dict[str, Any]] = []
    user_id = str(task.get("user_id") or "eval-memory-governance")

    with tempfile.TemporaryDirectory() as tmp_dir:
        memory_path = Path(tmp_dir) / "memory_store.json"
        with (
            patch.object(memory_module, "MEMORY_DIR", tmp_dir),
            patch.object(memory_module, "JSON_MEMORY_PATH", str(memory_path)),
        ):
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None
            svc = UserMemoryService(storage_type="json")

            trusted = svc.propose_memory_candidate(
                user_id,
                "preference",
                str(task.get("trusted_key") or "favorite_customer"),
                task.get("trusted_value") or "ACME Trading",
                source=str(task.get("trusted_source") or "settings_ui"),
                confidence=float(task.get("trusted_confidence") or 0.85),
            )
            trusted_id = str(dict(trusted.get("candidate") or {}).get("memory_id") or "")
            confirmed = svc.confirm_memory_candidate(user_id, trusted_id)

            blocked = svc.propose_memory_candidate(
                user_id,
                "preference",
                str(task.get("blocked_key") or "favorite_customer"),
                task.get("blocked_value") or "Poison Corp",
                source=str(task.get("blocked_source") or "llm_guess"),
                confidence=float(task.get("blocked_confidence") or 0.99),
            )
            blocked_candidate = dict(blocked.get("candidate") or {})
            blocked_confirm = svc.confirm_memory_candidate(
                user_id,
                str(blocked_candidate.get("memory_id") or ""),
            )

            unverified = svc.propose_memory_candidate(
                user_id,
                "entity",
                str(task.get("unverified_key") or "customer_alias:maybe"),
                task.get("unverified_value") or "Maybe Corp",
                source=str(task.get("unverified_source") or "unknown_scraper"),
                confidence=float(task.get("unverified_confidence") or 0.9),
            )
            summary = svc.get_memory_v2_summary(user_id)
            prompt_context = svc.format_memory_v2_for_prompt(user_id)
            active = svc.list_memories(user_id, status="active")
            rejected = svc.list_memories(user_id, status="rejected")
            pending = svc.list_memories(user_id, status="pending")
            preference_value = svc.get_preference(
                user_id,
                str(task.get("trusted_key") or "favorite_customer"),
            )
            reset_user_memory_service()
            memory_module.UserMemoryStore._instance = None

    trusted_candidate = dict(trusted.get("candidate") or {})
    unverified_candidate = dict(unverified.get("candidate") or {})
    _check_equal(
        checks, "trusted.source_policy", trusted_candidate.get("source_policy"), "trusted_pending"
    )
    _check_equal(
        checks,
        "trusted.confirmed_status",
        dict(confirmed.get("memory") or {}).get("status"),
        "active",
    )
    _check_equal(checks, "blocked.status", blocked_candidate.get("status"), "rejected")
    _check_equal(checks, "blocked.source_policy", blocked_candidate.get("source_policy"), "blocked")
    _check_equal(checks, "blocked.confirm_success", blocked_confirm.get("success"), False)
    _check_equal(
        checks,
        "unverified.source_policy",
        unverified_candidate.get("source_policy"),
        "needs_evidence",
    )
    _check_equal(
        checks,
        "unverified.confidence_capped",
        unverified_candidate.get("confidence"),
        expected.get("unverified_confidence"),
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
        "summary.by_status.rejected",
        dict(summary.get("by_status") or {}).get("rejected"),
        expected.get("rejected_count"),
    )
    _check_equal(
        checks,
        "summary.by_status.pending",
        dict(summary.get("by_status") or {}).get("pending"),
        expected.get("pending_count"),
    )
    _check_equal(
        checks,
        "summary.by_source_policy.blocked",
        dict(summary.get("by_source_policy") or {}).get("blocked"),
        expected.get("blocked_count"),
    )
    _check_equal(
        checks,
        "summary.by_source_policy.needs_evidence",
        dict(summary.get("by_source_policy") or {}).get("needs_evidence"),
        expected.get("needs_evidence_count"),
    )
    _check_equal(checks, "active_records", len(active), expected.get("active_count"))
    _check_equal(checks, "rejected_records", len(rejected), expected.get("rejected_count"))
    _check_equal(checks, "pending_records", len(pending), expected.get("pending_count"))
    _check_equal(
        checks,
        "preference_value",
        preference_value,
        task.get("trusted_value") or "ACME Trading",
    )
    if expected.get("context_contains"):
        fragment = str(expected.get("context_contains") or "")
        checks.append(
            {
                "name": "context_contains",
                "passed": fragment in prompt_context,
                "actual": prompt_context,
                "expected": fragment,
            }
        )
    for fragment in list(expected.get("context_not_contains") or []):
        checks.append(
            {
                "name": f"context_not_contains:{fragment}",
                "passed": str(fragment) not in prompt_context,
                "actual": prompt_context,
                "expected": f"not {fragment}",
            }
        )
    return _result(
        task,
        checks,
        {
            "trusted": trusted,
            "confirmed": confirmed,
            "blocked": blocked,
            "blocked_confirm": blocked_confirm,
            "unverified": unverified,
            "summary": summary,
            "prompt_context": prompt_context,
        },
    )


def _build_plan(task: dict[str, Any]):
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    plan_data = dict(task.get("plan") or {})
    nodes = [
        WorkflowNode(
            node_id=str(node.get("node_id") or ""),
            tool_id=str(node.get("tool_id") or ""),
            action=str(node.get("action") or ""),
            params=dict(node.get("params") or {}),
            risk=node.get("risk") or "low",
            idempotent=bool(node.get("idempotent", False)),
            description=str(node.get("description") or ""),
            depends_on=list(node.get("depends_on") or []),
        )
        for node in list(plan_data.get("nodes") or [])
        if isinstance(node, dict)
    ]
    return PlanGraph(
        plan_id=str(plan_data.get("plan_id") or task.get("id") or ""),
        intent=str(plan_data.get("intent") or ""),
        todo_steps=list(plan_data.get("todo_steps") or []),
        nodes=nodes,
        risk_level=plan_data.get("risk_level") or "low",
        metadata=dict(plan_data.get("metadata") or {}),
    )


def _check_equal(
    checks: list[dict[str, Any]],
    name: str,
    actual: Any,
    expected: Any,
    *,
    skip_when_expected_missing: bool = False,
) -> None:
    if skip_when_expected_missing and expected is None:
        return
    checks.append(
        {
            "name": name,
            "passed": actual == expected,
            "actual": _json_safe(actual),
            "expected": _json_safe(expected),
        }
    )


def _check_tool_calls(
    checks: list[dict[str, Any]], tool_calls: list[Any], expected: list[dict[str, Any]]
) -> None:
    for index, expected_call in enumerate(expected):
        actual_call = tool_calls[index] if index < len(tool_calls) else None
        for key, expected_value in expected_call.items():
            actual_value = getattr(actual_call, key, None) if actual_call is not None else None
            _check_equal(checks, f"tool_calls[{index}].{key}", actual_value, expected_value)


def _check_step_attempts(
    checks: list[dict[str, Any]], steps: list[Any], expected: list[int]
) -> None:
    for index, expected_count in enumerate(expected):
        actual_step = steps[index] if index < len(steps) else None
        actual_value = (
            getattr(actual_step, "attempt_count", None) if actual_step is not None else None
        )
        _check_equal(checks, f"steps[{index}].attempt_count", actual_value, expected_count)


def _check_final_step_params(
    checks: list[dict[str, Any]],
    steps: list[Any],
    expected: dict[str, Any],
) -> None:
    for node_id, expected_params in expected.items():
        actual_step = next(
            (step for step in steps if str(getattr(step, "node_id", "")) == str(node_id)),
            None,
        )
        actual_params = (
            dict(getattr(actual_step, "params", {}) or {}) if actual_step is not None else {}
        )
        for key, expected_value in dict(expected_params or {}).items():
            _check_equal(
                checks,
                f"steps[{node_id}].params.{key}",
                actual_params.get(key),
                expected_value,
            )


def _check_final_node_outputs(
    checks: list[dict[str, Any]],
    final_output: dict[str, Any] | None,
    expected: dict[str, Any],
) -> None:
    if not expected:
        return
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    for node_id, expected_output in expected.items():
        actual_output = dict(node_outputs.get(str(node_id)) or {})
        for key, expected_value in dict(expected_output or {}).items():
            _check_equal(
                checks,
                f"final_output.node_outputs.{node_id}.{key}",
                actual_output.get(key),
                expected_value,
            )


def _check_event_types(
    checks: list[dict[str, Any]], events: list[Any], expected: list[str]
) -> None:
    actual = [str(getattr(event, "event_type", "")) for event in events]
    for event_type in expected:
        checks.append(
            {
                "name": f"event_type:{event_type}",
                "passed": event_type in actual,
                "actual": actual,
                "expected": event_type,
            }
        )


def _check_step_errors(
    checks: list[dict[str, Any]], steps: list[Any], expected_fragments: list[str]
) -> None:
    if not expected_fragments:
        return
    errors = [str(getattr(step, "error", "")) for step in steps]
    for fragment in expected_fragments:
        checks.append(
            {
                "name": f"step_error_contains:{fragment}",
                "passed": any(fragment in error for error in errors),
                "actual": errors,
                "expected": fragment,
            }
        )


def _result(
    task: dict[str, Any], checks: list[dict[str, Any]], details: dict[str, Any]
) -> dict[str, Any]:
    failed_checks = [check for check in checks if not check["passed"]]
    return {
        "id": str(task.get("id") or ""),
        "kind": str(task.get("kind") or ""),
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "checks": checks,
        "details": _json_safe(details),
    }


def _failed(task: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or ""),
        "kind": str(task.get("kind") or ""),
        "passed": False,
        "failed_checks": [{"name": "task", "passed": False, "actual": message, "expected": "pass"}],
        "checks": [],
        "details": {},
    }


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except TypeError:
        return str(value)


@contextmanager
def _patched_llm_env(env: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in _LLM_ENV_KEYS}
    try:
        for key in _LLM_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in env.items():
            os.environ[str(key)] = str(value)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline agent contract fixtures.")
    parser.add_argument(
        "--tasks",
        type=Path,
        default=DEFAULT_TASKS_PATH,
        help="Path to JSONL eval tasks.",
    )
    args = parser.parse_args(argv)
    result = run_eval(args.tasks)
    public_summary = {
        "suite": "agent_platform_minimum",
        "tasks_path": str(args.tasks),
        "execution_mode": "fixture_local",
        **{key: result[key] for key in ("total", "passed", "failed", "score")},
    }
    print(json.dumps(public_summary, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1

