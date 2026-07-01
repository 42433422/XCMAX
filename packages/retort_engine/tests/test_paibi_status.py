from __future__ import annotations

import json

from retort_engine.paibi_status import (
    _extract_last_json_object,
    analyze_task_blockers,
    normalize_llm_scores,
    parallel_summary,
    summarize_task,
    unblock_tasks_from_blockers,
)


def test_summarize_task_extracts_scores_from_subtask_logs() -> None:
    payload = {
        "task": {
            "id": "task-1",
            "status": "completed",
            "subTasks": [
                {
                    "id": "sub-1",
                    "title": "score",
                    "status": "completed",
                    "progress": 100,
                    "logs": [
                        {"content": "starting"},
                        {"content": json.dumps({"score_suggestion": 83, "scores": [{"dimension": "calibrated_overall", "value": 83, "reason": "ok"}]})},
                    ],
                }
            ],
        }
    }

    status = summarize_task(payload)

    assert status["task_id"] == "task-1"
    assert status["status"] == "completed"
    assert status["scores"][0]["dimension"] == "calibrated_overall"
    assert status["scores"][0]["value"] == 83
    assert status["subtasks"][0]["log_count"] == 2


def test_summarize_task_accepts_flat_task_payload() -> None:
    status = summarize_task({"id": "flat", "status": "running", "subtasks": []})

    assert status["task_id"] == "flat"
    assert status["status"] == "running"
    assert status["scores"] == []


def test_extract_last_json_object_keeps_last_scored_candidate() -> None:
    first = {"score_suggestion": 70}
    middle = {"other": "ignored unless no scored payload"}
    last = {"score_suggestion": 91}

    result = _extract_last_json_object(f"{json.dumps(first)}\n{json.dumps(middle)}\n{json.dumps(last)}")

    assert result == last


def test_extract_last_json_object_falls_back_to_last_plain_object() -> None:
    result = _extract_last_json_object('noise {"a": 1} more {"b": 2}')

    assert result == {"b": 2}


def test_extract_last_json_object_ignores_incomplete_json() -> None:
    result = _extract_last_json_object('{"score_suggestion": 70\n{"score_suggestion": 82}')

    assert result == {"score_suggestion": 82}


def test_normalize_scores_clamps_values_and_filters_dimensions() -> None:
    scores = normalize_llm_scores(
        {
            "scores": [
                {"dimension": "calibrated_overall", "value": 111, "reason": "too high", "evidence": ["x"]},
                {"dimension": "unknown", "value": 50},
                {"dimension": "product_level", "value": -5},
                {"dimension": "architecture_depth", "value": "bad"},
            ]
        }
    )

    assert scores == [
        {"dimension": "calibrated_overall", "value": 100.0, "reason": "too high", "evidence": ["x"]},
        {"dimension": "product_level", "value": 0.0, "reason": "LLM score from Retort scoring prompt.", "evidence": []},
    ]


def test_normalize_scores_uses_score_suggestion_when_overall_missing() -> None:
    scores = normalize_llm_scores({"score_suggestion": 77})

    assert scores == [
        {
            "dimension": "calibrated_overall",
            "value": 77.0,
            "reason": "LLM score_suggestion normalized as calibrated_overall.",
            "evidence": [],
        }
    ]


def test_normalize_scores_returns_empty_for_invalid_payload() -> None:
    assert normalize_llm_scores(None) == []
    assert normalize_llm_scores({"score_suggestion": "not-number"}) == []


def test_blocker_detection_marks_worker_capacity_from_busy_logs() -> None:
    blockers = analyze_task_blockers(
        {
            "task_id": "task-1",
            "status": "running",
            "logs_excerpt": "执行器忙 busy",
            "subtasks": [{"id": "sub-1", "status": "pending", "depends_on": []}],
        }
    )

    assert blockers[0]["kind"] == "worker_capacity_limit"
    assert blockers[0]["pending_subtask_count"] == 1


def test_summarize_task_marks_zero_progress_dispatch_wait_as_stale() -> None:
    status = summarize_task(
        {
            "task": {
                "id": "task-stale",
                "status": "running",
                "subTasks": [
                    {
                        "id": "sub-stale",
                        "title": "Retort scoring",
                        "status": "running",
                        "progress": 0,
                        "logs": [{"content": "依赖已满足，等待派发。 未提供远程仓库，将使用工作设备本地目录"}],
                    }
                ],
            }
        }
    )

    assert status["scores"] == []
    assert status["blockers"][0]["kind"] == "stale_dispatch"
    assert status["blockers"][0]["action"] == "retry_with_idle_tool_slot"
    assert status["unblock_tasks"][0]["blocker_kind"] == "stale_dispatch"
    assert "重新派发" in status["unblock_tasks"][0]["title"]


def test_blocker_detection_classifies_executor_missing() -> None:
    blockers = analyze_task_blockers(
        {
            "status": "running",
            "logs_excerpt": "",
            "subtasks": [{"id": "sub-1", "status": "failed", "blocked": True, "last_error": "缺少自动改码执行器"}],
        }
    )

    assert blockers[0]["kind"] == "executor_missing"
    assert blockers[0]["action"] == "install_or_select_executor"


def test_blocker_detection_classifies_workspace_clone_race() -> None:
    blockers = analyze_task_blockers(
        {
            "status": "running",
            "logs_excerpt": "git clone --no-hardlinks failed fetch-pack tmp_pack",
            "subtasks": [{"id": "sub-1", "status": "failed", "blocked": True}],
        }
    )

    assert blockers[0]["kind"] == "workspace_clone_race"


def test_blocker_detection_classifies_device_offline() -> None:
    blockers = analyze_task_blockers(
        {
            "status": "running",
            "logs_excerpt": "device offline",
            "subtasks": [{"id": "sub-1", "status": "blocked", "blocked": True}],
        }
    )

    assert blockers[0]["kind"] == "device_offline"


def test_blocker_detection_classifies_dependency_wait() -> None:
    blockers = analyze_task_blockers(
        {
            "status": "running",
            "logs_excerpt": "depends on previous 前置",
            "subtasks": [{"id": "sub-1", "status": "failed", "blocked": True}],
        }
    )

    assert blockers[0]["kind"] == "dependency_wait"


def test_blocker_detection_classifies_timeout() -> None:
    blockers = analyze_task_blockers(
        {
            "status": "running",
            "logs_excerpt": "timeout 超时",
            "subtasks": [{"id": "sub-1", "status": "failed", "blocked": True}],
        }
    )

    assert blockers[0]["kind"] == "timeout"


def test_blocker_detection_adds_task_level_failure() -> None:
    blockers = analyze_task_blockers({"task_id": "task-1", "status": "failed", "subtasks": []})

    assert blockers == [{"kind": "task_blocked", "action": "inspect_task_logs_and_retry", "task_id": "task-1", "status": "failed"}]


def test_parallel_summary_counts_statuses_and_devices() -> None:
    summary = parallel_summary(
        {
            "status": "running",
            "subtasks": [
                {"status": "completed", "device_name": "a"},
                {"status": "running", "device_name": "a"},
                {"status": "failed", "blocked": True, "device_name": "b"},
            ],
        }
    )

    assert summary["subtask_count"] == 3
    assert summary["status_counts"] == {"completed": 1, "running": 1, "failed": 1}
    assert summary["device_count"] == 2
    assert summary["has_blockers"] is True


def test_unblock_tasks_generate_targeted_acceptance() -> None:
    blockers = [
        {"kind": "device_offline", "subtask_id": "a"},
        {"kind": "executor_missing", "subtask_id": "b"},
        {"kind": "dependency_wait", "subtask_id": "c"},
        {"kind": "timeout", "subtask_id": "d"},
        {"kind": "worker_capacity_limit", "task_id": "e"},
        {"kind": "workspace_clone_race", "subtask_id": "f"},
        {"kind": "unknown", "subtask_id": "g"},
    ]

    tasks = unblock_tasks_from_blockers(blockers)

    assert [task["task_id"] for task in tasks] == [f"para-unblock-{index:02d}" for index in range(1, 8)]
    assert {task["owner_hint"] for task in tasks} == {"runtime", "scheduler"}
    assert "离线" in tasks[0]["title"]
    assert "执行器" in tasks[1]["title"]
    assert "前置" in tasks[2]["title"]
    assert "超时" in tasks[3]["title"]
    assert "worker" in tasks[4]["title"]
    assert "隔离" in tasks[5]["title"]
    assert "重试" in tasks[6]["title"]
