import json
import sqlite3

from modstore_server.self_maintenance_loop_runner import (
    _PARA_GUEST_AUTH_CACHE,
    _assess_branch_auto_merge_policy,
    _employee_result_ok,
    _extract_failure_reason,
    _find_delivery_validation,
    _guest_auth_headers,
    _has_high_risk_report,
    _is_transient_employee_dispatch_failure,
    _load_loop_memory,
    _qa_task_text,
    _resume_review_qa_candidate,
    _review_task_text,
    _self_maintenance_actor_user_id,
    _structured_report_gate,
    _update_loop_memory,
    clean_baseline_path,
    close_loop_memory_items,
    ensure_clean_baseline,
    loop_memory_path,
)


def _stats(line_changes=12, binary_files=None):
    return {
        "additions": line_changes,
        "binary_files": binary_files or [],
        "deletions": 0,
        "files": {},
        "line_changes": line_changes,
    }


def test_dynamic_low_risk_policy_allows_self_maintenance_code_and_tests(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁，让流程走到 dynamic_low_risk 策略（本测试验证 dynamic_low_risk 逻辑）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_dynamic_low_risk_policy_blocks_marker_only_when_memory_requires_executable_change():
    files = ["成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_loop_status.py"]
    memory = {
        "open_items": [
            {
                "kind": "review_qa_failure",
                "reason": "marker-only status file is not executable evidence",
            }
        ]
    }

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "marker_only_diff_requires_executable_change"


def test_dynamic_low_risk_policy_blocks_forbidden_paths():
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is False
    assert result["reason"] == "changed_files_match_forbidden_globs"


def test_forbidden_paths_override_legacy_allowed_globs(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_GLOBS",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    )
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is False
    assert result["reason"] == "changed_files_match_forbidden_globs"


def test_dynamic_low_risk_policy_blocks_name_only_numstat_mismatch():
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]
    diff_stats = {
        "binary_files": [],
        "changed_files": [
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
        ],
        "files": {
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py": {
                "additions": 1,
                "deletions": 0,
            },
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py": {
                "additions": 1,
                "deletions": 0,
            },
        },
        "line_changes": 2,
        "source": "git_diff_numstat",
    }

    result = _assess_branch_auto_merge_policy(files, diff_stats)

    assert result["ok"] is False
    assert result["reason"] == "changed_files_diff_stats_mismatch"


def test_dynamic_low_risk_policy_allows_project_context_followup_files(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁 + 放宽 risk_score_v1 阈值，让流程走到 dynamic_low_risk 策略
    # （本测试验证 dynamic_low_risk 逻辑，不验证 risk_score 评分）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", "100")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/models_project_context.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_project_context_followups.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=512))

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_dynamic_low_risk_policy_allows_self_evolution_knowledge_files(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁 + 放宽 risk_score_v1 阈值，让流程走到 dynamic_low_risk 策略
    # （本测试验证 dynamic_low_risk 逻辑，不验证 risk_score 评分）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", "100")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_evolution_knowledge.py",
        "FHD/XCAGI/kb/fixes/2026-06-18-modstore-narrow-ci-pycache-prefix.md",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_evolution_knowledge.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=580))

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_dynamic_low_risk_policy_blocks_large_changes(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_LINES", "10")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=11))

    assert result["ok"] is False
    assert result["reason"] == "too_many_changed_lines_for_dynamic_auto_merge"


def test_transient_para_api_outbox_failure_is_retryable():
    result = {
        "result": {
            "outputs": [
                {
                    "error": "Para API 调用失败，已写入 outbox: [Errno 61] Connection refused",
                    "status": "para_api_failed_outboxed",
                }
            ]
        }
    }

    assert _is_transient_employee_dispatch_failure(result) is True


def test_business_failure_is_not_retryable():
    result = {"result": {"outputs": [{"error": "pytest failed: assertion error"}]}}

    assert _is_transient_employee_dispatch_failure(result) is False


def test_guest_auth_headers_uses_injected_token(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_AUTH_TOKEN", "local-token")

    headers = _guest_auth_headers("http://127.0.0.1:3001")

    assert headers == {"Authorization": "Bearer local-token"}


def test_guest_auth_headers_uses_persistent_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "para_auth.json"
    monkeypatch.delenv("MODSTORE_PARA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_AUTH_CACHE", str(cache_path))
    _PARA_GUEST_AUTH_CACHE.clear()
    cache_path.write_text(
        json.dumps(
            {
                "api_base": "http://127.0.0.1:3001",
                "expires_at": 4102444800,
                "token": "cached-token",
            }
        ),
        encoding="utf-8",
    )

    headers = _guest_auth_headers("http://127.0.0.1:3001/")

    assert headers == {"Authorization": "Bearer cached-token"}
    assert _PARA_GUEST_AUTH_CACHE["http://127.0.0.1:3001"][0] == "cached-token"


def test_guest_auth_headers_can_mint_local_guest_token(monkeypatch, tmp_path):
    cache_path = tmp_path / "para_auth.json"
    db_path = tmp_path / "devfleet.db"
    monkeypatch.delenv("MODSTORE_PARA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_AUTH_CACHE", str(cache_path))
    monkeypatch.setenv("MODSTORE_PARA_DB_FILE", str(db_path))
    monkeypatch.setenv("MODSTORE_PARA_JWT_SECRET", "test-secret")
    _PARA_GUEST_AUTH_CACHE.clear()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("create table users (id text primary key, email text not null)")
        conn.execute(
            "insert into users (id, email) values (?, ?)",
            ("guest-id", "guest@devfleet.local"),
        )

    headers = _guest_auth_headers("http://127.0.0.1:3001")
    token = headers["Authorization"].replace("Bearer ", "", 1)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert token.count(".") == 2
    assert cache["api_base"] == "http://127.0.0.1:3001"
    assert cache["token"] == token


def test_self_maintenance_actor_defaults_to_platform_identity(monkeypatch):
    # 默认无 env 覆盖时走平台身份 0：chat_dispatch_via_session 不再过个人
    # llm_calls 配额闸，避免历史「记到 owner 配额→额度耗尽→403 死循环」根因。
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_USER_ID", raising=False)

    assert _self_maintenance_actor_user_id() == 0


def test_self_maintenance_actor_honors_env_override(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_USER_ID", "7")

    assert _self_maintenance_actor_user_id() == 7


def test_self_maintenance_actor_falls_back_to_platform_on_bad_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_USER_ID", "not-an-int")

    assert _self_maintenance_actor_user_id() == 0


def test_employee_result_rejects_e2e_codex_timeout():
    result = {
        "result": {
            "ok": True,
            "status": "completed",
            "outputs": [
                {"message": "[e2e-agent] Codex CLI 失败: Codex CLI timeout after 600000ms"}
            ],
        }
    }

    assert _employee_result_ok(result) is False


def test_extract_failure_reason_picks_up_delivery_validation_failure():
    # delivery_validation 由 Para 远端返回，嵌在 result.result.outputs[].para_result
    # 等任意层级。模拟真实结构：change_delivery.ok=true（代码已交付）但验证命令失败。
    result = {
        "result": {
            "ok": False,
            "status": "failed",
            "outputs": [
                {
                    "handler": "para_delegate",
                    "para_result": {
                        "delivery_validation": {
                            "commands": [
                                {
                                    "command": "-m pytest tests/test_x.py",
                                    "exit_code": 1,
                                    "output_tail": "FAILED tests/test_x.py::test_safe_branch_name",
                                },
                                {"command": "-m py_compile main.py", "exit_code": 0},
                            ],
                        }
                    },
                }
            ],
        }
    }

    reason = _extract_failure_reason(result, {})

    assert "delivery_validation_failed" in reason
    assert "exit=1" in reason
    assert "pytest tests/test_x.py" in reason


def test_extract_failure_reason_falls_back_when_no_delivery_validation():
    # 无 delivery_validation 时走原有兜底逻辑，返回非空原因
    result = {"result": {"ok": False, "status": "completed"}}

    reason = _extract_failure_reason(result, {})

    assert reason and reason != "delivery_validation_failed"


def test_resume_review_qa_candidate_uses_failed_review_branch():
    memory = {
        "open_items": [
            {"kind": "failed_steps", "run_id": "r1", "steps": ["review"]},
        ],
        "recent_runs": [
            {
                "branch": "devfleet/codex/sub-1",
                "para_task_id": "task-1",
                "run_id": "r1",
                "status": "failed",
            }
        ],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-1",
        "failed_run_id": "r1",
        "failed_steps": ["review"],
        "para_task_id": "task-1",
        "reason": "resume_failed_review_or_qa",
    }


def test_resume_review_qa_candidate_uses_human_strategy_branch():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/sub-2",
                "kind": "human_strategy_approval",
                "reason": "changed_files_match_forbidden_globs",
                "run_id": "r2",
                "task_id": "task-2",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-2",
        "failed_run_id": "r2",
        "failed_steps": ["qa"],
        "para_task_id": "task-2",
        "reason": "resume_human_strategy_candidate",
    }


def test_resume_review_qa_candidate_stops_when_latest_policy_has_real_risk():
    memory = {
        "last_policy_decision": {
            "action": "await_human_strategy_approval",
            "reason": "review_or_qa_reported_risk",
        },
        "open_items": [
            {
                "branch": "devfleet/codex/sub-2",
                "kind": "human_strategy_approval",
                "reason": "changed_files_match_forbidden_globs",
                "run_id": "r2",
                "task_id": "task-2",
            }
        ],
        "recent_runs": [],
    }

    assert _resume_review_qa_candidate(memory) is None


def test_report_only_review_and_qa_prompt_pin_target_branch(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "feat/base")
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")

    review = _review_task_text("run-1", "devfleet/codex/sub-1", {})
    qa = _qa_task_text("run-1", "devfleet/codex/sub-1", {})

    assert "Target branch to inspect: `devfleet/codex/sub-1`" in review
    assert "Target branch to verify: `devfleet/codex/sub-1`" in qa
    assert "Do not inspect your own report-only task branch" in review
    assert "Do not inspect your own report-only task branch" in qa
    assert "file:///tmp/repo.git" in qa


def test_high_risk_report_detects_standalone_qa_fail():
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                "FAIL\n\n"
                "Blocking QA findings:\n"
                "Recommendation: do not merge this target as-is."
            ),
        }
    ]

    assert _has_high_risk_report(steps) is True


def test_structured_report_gate_requires_qa_json_pass():
    steps = [
        {
            "step": "review",
            "report_excerpt": (
                'SELF_MAINTENANCE_REVIEW_JSON: {"max_severity":"low",'
                '"blocking_findings":[],"risk_class":"low","target_branch_available":true,'
                '"tested_commands":[]}'
            ),
        },
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                '"tested_commands":[{"command":"pytest focused","exit_code":0,"status":"passed"}],'
                '"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        },
    ]

    assert _structured_report_gate(steps)["ok"] is True


def test_structured_report_gate_blocks_missing_or_failed_qa_json():
    missing = [{"step": "qa", "report_excerpt": "PASS in prose only"}]
    failed = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"FAIL","blocking_findings":["x"],'
                '"tested_commands":[],"target_branch_available":true,'
                '"test_delta":{"new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"high"}'
            ),
        }
    ]

    assert _structured_report_gate(missing)["reason"] == "missing_structured_qa_result"
    assert _structured_report_gate(failed)["reason"] == "structured_qa_verdict_not_pass"


def test_ensure_clean_baseline_writes_default_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE", str(tmp_path / "baseline.json"))

    baseline = ensure_clean_baseline()

    assert clean_baseline_path().exists()
    assert baseline["baseline_id"] == "initial-current-known-failures-2026-06-18"
    assert baseline["pytest"]["allowed_failure_count"] == 80


def test_close_loop_memory_items_moves_open_item_to_closed(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "kind": "human_strategy_approval",
                        "reason": "changed_files_outside_dynamic_low_risk_scope",
                        "run_id": "run-1",
                    }
                ],
                "recent_runs": [],
            }
        ),
        encoding="utf-8",
    )

    result = close_loop_memory_items(
        actor="test",
        resolution_reason="kb scope now allows approved knowledge artifacts",
        run_ids=["run-1"],
    )
    memory = _load_loop_memory()

    assert result["closed_count"] == 1
    assert memory["open_items"] == []
    assert memory["closed_items"][0]["actor"] == "test"
    assert memory["closed_items"][0]["original_item"]["run_id"] == "run-1"


def test_update_loop_memory_closes_resumed_item_after_success(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "branch": "devfleet/codex/sub-1",
                        "kind": "failed_steps",
                        "run_id": "failed-run",
                        "steps": ["qa"],
                        "task_id": "task-1",
                    }
                ],
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )

    _update_loop_memory(
        {
            "branch": "devfleet/codex/sub-1",
            "completed_at": "2026-06-18T00:00:00+00:00",
            "para_task_id": "task-1",
            "policy_decision": {"action": "auto_continue", "reason": "no_code_branch"},
            "resume_candidate": {
                "branch": "devfleet/codex/sub-1",
                "failed_run_id": "failed-run",
                "failed_steps": ["qa"],
                "para_task_id": "task-1",
            },
            "run_id": "new-run",
            "status": "completed",
            "steps": [{"ok": True, "step": "qa"}],
        },
        {"reason": "force"},
    )
    memory = _load_loop_memory()

    assert memory["open_items"] == []
    assert memory["closed_items"][0]["original_item"]["run_id"] == "failed-run"
    assert memory["last_resolution_record"]["closed_count"] == 1


# ---------------------------------------------------------------------------
# _find_delivery_validation: 直接单元测试（2026-07-20 修复核心）
# ---------------------------------------------------------------------------


class TestFindDeliveryValidation:
    """验证 `_find_delivery_validation` 在 Para 远端返回结构中递归定位
    delivery_validation dict 的能力。"""

    def test_find_delivery_validation_single_level_nesting(self):
        """单层嵌套：result.result.outputs[0].para_result.delivery_validation。"""
        dv = {"commands": [{"exit_code": 1, "command": "pytest"}]}
        result = {
            "result": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "para_result": {"delivery_validation": dv},
                    }
                ]
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_deep_nesting(self):
        """depth=4 多层嵌套，模拟 Para 真实结构
        result.result.outputs[0].response.data.subtask.delivery_validation。"""
        dv = {"commands": [{"exit_code": 2}]}
        result = {
            "result": {
                "outputs": [
                    {
                        "response": {
                            "data": {
                                "subtask": {"delivery_validation": dv},
                            },
                        },
                    }
                ]
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_depth_truncation(self):
        """depth>6 时返回 None：构造 7 层嵌套，delivery_validation 在第 7 层。"""
        dv = {"commands": [{"exit_code": 1}]}
        # 嵌套结构：a -> b -> c -> d -> e -> f -> g -> delivery_validation
        # 调用 _find_delivery_validation(top) 时 depth=0, 进入 a 后 depth=1,
        # 进入 b 后 depth=2, ..., 进入 g 后 depth=7 → 立即返回 None
        nested = {"delivery_validation": dv}
        for key in ("g", "f", "e", "d", "c", "b", "a"):
            nested = {key: nested}

        found = _find_delivery_validation(nested)

        assert found is None

    def test_find_delivery_validation_list_truncation(self):
        """列表超过 12 项时只搜前 12 项：delivery_validation 放在第 13 项应返回 None。"""
        dv = {"commands": [{"exit_code": 1}]}
        items = [{"index": i} for i in range(12)] + [{"delivery_validation": dv}]
        result = {"items": items}

        found = _find_delivery_validation(result)

        assert found is None

    def test_find_delivery_validation_skips_non_dict(self):
        """delivery_validation 字段值为字符串/list 时返回 None（只识别 dict）。"""
        result_str = {"delivery_validation": "not a dict"}
        result_list = {"delivery_validation": ["not", "a", "dict"]}

        assert _find_delivery_validation(result_str) is None
        assert _find_delivery_validation(result_list) is None

    def test_find_delivery_validation_empty_dict(self):
        """空 dict 输入返回 None。"""
        assert _find_delivery_validation({}) is None

    def test_find_delivery_validation_multiple_occurrences(self):
        """多个 delivery_validation 时返回第一个（DFS 顺序）。"""
        dv_first = {"commands": [{"exit_code": 1}], "marker": "first"}
        dv_second = {"commands": [{"exit_code": 2}], "marker": "second"}
        result = {
            "result": {
                "delivery_validation": dv_first,
                "nested": {"delivery_validation": dv_second},
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv_first

    def test_find_delivery_validation_in_list_items(self):
        """列表项中包含 delivery_validation 能被找到。"""
        dv = {"commands": [{"exit_code": 1}]}
        result = {"outputs": [{"name": "skip"}, {"delivery_validation": dv}]}

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_commands_with_exit_code_none(self):
        """exit_code=None 的 command 不视为失败：_find_delivery_validation 仍能找到 dv，
        但 _extract_failure_reason 不会返回 delivery_validation_failed。"""
        dv = {"commands": [{"exit_code": None, "command": "pytest"}]}
        result = {"result": {"ok": False, "delivery_validation": dv}}

        # _find_delivery_validation 找到 dict
        found = _find_delivery_validation(result)
        assert found is dv

        # _extract_failure_reason 不把 exit_code=None 视为失败，落到 fallback
        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" not in reason

    def test_find_delivery_validation_commands_with_exit_code_zero(self):
        """exit_code=0 的 command 不视为失败。"""
        dv = {"commands": [{"exit_code": 0, "command": "pytest"}]}
        result = {"result": {"ok": False, "delivery_validation": dv}}

        found = _find_delivery_validation(result)
        assert found is dv

        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" not in reason

    def test_find_delivery_validation_commands_with_non_zero_exit(self):
        """exit_code≠0 的 command 视为失败：_extract_failure_reason 返回 delivery_validation_failed。"""
        dv = {
            "commands": [
                {"exit_code": 1, "command": "pytest tests/x.py"},
                {"exit_code": 0, "command": "ruff check"},
            ]
        }
        result = {"result": {"ok": False, "delivery_validation": dv}}

        found = _find_delivery_validation(result)
        assert found is dv

        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason

    def test_find_delivery_validation_returns_none_for_none_input(self):
        """None 输入返回 None。"""
        assert _find_delivery_validation(None) is None

    def test_find_delivery_validation_returns_none_for_string_input(self):
        """字符串输入返回 None。"""
        assert _find_delivery_validation("not a dict") is None


# ---------------------------------------------------------------------------
# _extract_failure_reason: 端到端优先级测试
# ---------------------------------------------------------------------------


class TestExtractFailureReasonEndToEnd:
    """验证 `_extract_failure_reason` 各分支优先级与 fallback 行为。"""

    def test_priority_handler_failed_message(self):
        """handler_failed + handler_failed_message 优先级最高。"""
        result = {
            "handler_failed": True,
            "handler_failed_message": "codex cli crashed",
            "result": {"ok": False, "delivery_validation": {"commands": [{"exit_code": 1}]}},
        }

        reason = _extract_failure_reason(result, {"error": "para error"})

        assert reason.startswith("handler_failed:")
        assert "codex cli crashed" in reason

    def test_priority_path_guard_violation(self):
        """path_guard.ok=False 提取 violations（无 handler_failed 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "path_guard": {
                    "checked": True,
                    "ok": False,
                    "violations": [
                        {"path": "forbidden/x.py", "reason": "outside_scope"},
                    ],
                },
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("path_guard_violation:")
        assert "forbidden/x.py" in reason
        assert "outside_scope" in reason

    def test_priority_inner_outputs_failure(self):
        """outputs[].ok=False 提取 handler/error（无 handler_failed/path_guard 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [
                    {
                        "handler": "code_writer",
                        "ok": False,
                        "error": "syntax error in generated file",
                        "detail": "line 42",
                    }
                ],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("output_failed:")
        assert "handler=code_writer" in reason
        assert "syntax error" in reason

    def test_priority_delivery_validation_failed(self):
        """delivery_validation.commands[].exit_code≠0 提取失败命令（2026-07-20 修复核心）。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "ok": True,
                        "para_result": {
                            "delivery_validation": {
                                "commands": [
                                    {
                                        "command": "pytest tests/test_x.py",
                                        "exit_code": 1,
                                        "output_tail": "FAILED tests/test_x.py::test_a",
                                    }
                                ]
                            }
                        },
                    }
                ],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason
        assert "pytest tests/test_x.py" in reason

    def test_priority_para_error(self):
        """para_meta.error 提取（无 handler/path_guard/outputs/dv 时优先）。"""
        result = {"result": {"ok": False, "status": "completed"}}
        para_meta = {"error": "Para task timeout 900s"}

        reason = _extract_failure_reason(result, para_meta)

        assert reason.startswith("para_error:")
        assert "Para task timeout 900s" in reason

    def test_priority_para_status(self):
        """para_meta.para_status 非 completed/ok/success 提取。"""
        result = {"result": {"ok": False, "status": "completed"}}
        para_meta = {"para_status": "failed"}

        reason = _extract_failure_reason(result, para_meta)

        assert reason == "para_status=failed"

    def test_priority_inner_status_failed(self):
        """inner.status=failed 提取（无 para_meta 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "status": "failed",
                "error": "agent gave up after max rounds",
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("inner_status=failed:")
        assert "agent gave up" in reason

    def test_priority_report_marker_blocked_by_risk_middleware(self):
        """report 含 'blocked by risk middleware' 返回 blocked_by_risk_middleware。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [{"message": "task blocked by risk middleware: forbidden path"}],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason == "blocked_by_risk_middleware"

    def test_priority_report_marker_codex_cli_failed(self):
        """report 含 '[e2e-agent] codex cli 失败' 返回 codex_cli_failed。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [
                    {"message": "[e2e-agent] codex cli 失败: exit code 1"}
                ],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason == "codex_cli_failed"

    def test_fallback_ok_false_unknown_reason(self):
        """所有分支都不匹配时返回 'ok_false_unknown_reason'。"""
        result = {"result": {"ok": False, "status": "completed"}}

        reason = _extract_failure_reason(result, {})

        assert reason == "ok_false_unknown_reason"

    def test_delivery_validation_with_multiple_failed_commands(self):
        """多个失败命令拼接（最多 3 个）。"""
        dv = {
            "commands": [
                {"exit_code": 1, "command": "pytest a"},
                {"exit_code": 2, "command": "pytest b"},
                {"exit_code": 3, "command": "pytest c"},
                {"exit_code": 4, "command": "pytest d"},  # 超过 3 个，应被截断
            ]
        }
        result = {"result": {"ok": False, "delivery_validation": dv}}

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason
        assert "exit=2" in reason
        assert "exit=3" in reason
        # 第 4 个不应出现
        assert "exit=4" not in reason

    def test_delivery_validation_truncates_long_output(self):
        """长 output_tail 截断到 120 字符。"""
        long_tail = "x" * 500
        dv = {
            "commands": [
                {"exit_code": 1, "command": "pytest", "output_tail": long_tail}
            ]
        }
        result = {"result": {"ok": False, "delivery_validation": dv}}

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        # output_tail 被截断到 120 字符
        assert ("tail=" + "x" * 120) in reason
        # 不应包含完整的 500 字符
        assert "x" * 200 not in reason
