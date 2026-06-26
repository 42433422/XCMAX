"""进化引擎应排除配额/基建类失败（非 prompt 问题），避免配额耗尽时空转狂改 prompt。

复现 2026-06 生产实测根因：员工执行 99.6% 失败源于 ``403: 配额不足: llm_calls``，
进化引擎却把它当 prompt 问题每天瞎改 2000+ 次。此测试钉死：基建类失败不进入进化候选。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modstore_server import employee_autonomy_service as svc
from modstore_server.llm_failure_classifier import classify_failure_kind
from modstore_server.models import EmployeeExecutionMetric, get_session_factory, init_db


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


def _add_failures(session, employee_id: str, n: int, error: str) -> None:
    now = datetime.now(timezone.utc)
    kind = classify_failure_kind(error)
    for _ in range(n):
        session.add(
            EmployeeExecutionMetric(
                user_id=0,
                employee_id=employee_id,
                task="t",
                status="failed",
                error=error,
                failure_kind=kind,
                created_at=now,
            )
        )


def test_evolution_excludes_infra_quota_failures():
    sf = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with sf() as s:
        _add_failures(s, "emp-quota", 6, "403: 配额不足: llm_calls")  # 基建：应排除
        _add_failures(s, "emp-ratelimit", 5, "429 rate limit exceeded")  # 基建：应排除
        _add_failures(s, "emp-real", 4, "tool call returned invalid json")  # 真 prompt 失败：入选
        _add_failures(s, "emp-fewreal", 2, "bad output format")  # 真但 < 阈值：不入选
        s.commit()
        cands = dict(
            svc._evolution_failure_candidates(s, cutoff=cutoff, min_failures=3, limit=20)
        )
    assert cands.get("emp-real") == 4
    assert "emp-quota" not in cands
    assert "emp-ratelimit" not in cands
    assert "emp-fewreal" not in cands


def test_mixed_failures_only_count_prompt_addressable():
    sf = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with sf() as s:
        _add_failures(s, "emp-mixed", 4, "403: 配额不足: llm_calls")  # 基建：不计
        _add_failures(s, "emp-mixed", 3, "handler raised ValueError")  # 真：计
        s.commit()
        cands = dict(
            svc._evolution_failure_candidates(s, cutoff=cutoff, min_failures=3, limit=20)
        )
    assert cands.get("emp-mixed") == 3
