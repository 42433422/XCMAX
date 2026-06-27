from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.task_dispatch_plan import build_task_dispatch_plan


def test_task_dispatch_plan_uses_latest_llm_tasks_and_enqueues(tmp_path: Path) -> None:
    project = tmp_path / "project"
    retort_dir = project / ".retort"
    retort_dir.mkdir(parents=True)
    (retort_dir / "llm_reviews.jsonl").write_text(
        json.dumps(
            {
                "json_result": {
                    "employee_tasks": [
                        {
                            "title": "盲测质量基准",
                            "owner_hint": "review_employee",
                            "acceptance": "新增未知PR样本仍低误报",
                            "evidence_required": "样本集、结论、误报统计",
                        },
                        {
                            "title": "权限降级发布探针",
                            "owner_hint": "security_employee",
                            "acceptance": "无admin仅write时安全发布回滚",
                            "evidence_required": ["接口响应", "删除证明"],
                        },
                    ]
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_task_dispatch_plan(project, enqueue=True)

    assert result["status"] == "ready"
    assert result["summary"]["source_llm_task_count"] == 2
    assert result["summary"]["ready_task_count"] == 2
    assert result["summary"]["queued_dispatch_count"] == 2
    assert result["summary"]["all_tasks_have_acceptance"] is True
    assert all(task["queue_id"] for task in result["tasks"])
    assert (retort_dir / "employee_queue.jsonl").read_text(encoding="utf-8").count("retort_task_dispatch_plan") == 2
    assert validate_contract("task_dispatch_plan_result", result)["valid"] is True
