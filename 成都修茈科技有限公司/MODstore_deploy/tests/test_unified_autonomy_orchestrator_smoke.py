"""unified_autonomy_orchestrator 烟雾测试。

覆盖 dry-run incident→policy→execute 全链路：
- 端到端 dry-run（mock 掉 cluster_status / DB / 外部依赖）
- _scope 中文别名映射
- _priority 计算边界（security/payment +25、down/outage +18、scope weight、[0,100] 钳制）
- _resource_plan mock（cluster_status 正常 / 异常路径）
- 未知 scope 容错（fallback 到 "global"）
- 重复 event_id 调用幂等（不抛错）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# 确保 MODstore_deploy 在 sys.path 上，使 `from modstore_server...` 在任意 cwd 下都可导入。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modstore_server import models  # noqa: E402
from modstore_server.unified_autonomy_orchestrator import (  # noqa: E402
    KNOWN_SCOPES,
    _priority,
    _resource_plan,
    _scope,
    orchestrate_incident,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """每个用例独立 SQLite + 初始化 schema。"""
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "orch.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def _insert_incident(
    *,
    event_type: str = "on_error",
    source: str = "fhd",
    payload: Dict[str, Any] | None = None,
) -> int:
    """插入一条 IncidentEvent 并返回其 id。"""
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type=event_type,
            source=source,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        s.add(ev)
        s.commit()
        return ev.id


# ---------------------------------------------------------------------------
# 1. dry-run incident→policy→execute 全链路
# ---------------------------------------------------------------------------


def test_orchestrate_incident_full_chain_dry_run(fresh_db, monkeypatch):
    """端到端 dry-run：incident → _scope → _priority → route_for_incident → _resource_plan → commit。

    所有外部依赖（cluster_status / Redis / GitHub API）均 mock。
    """
    fake_cluster = {
        "ok": True,
        "leader": {"node_id": "node-1", "priority": 10},
        "active_nodes": [{"node_id": "node-1"}],
        "stale_nodes": [],
        "backend": "file",
    }
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: fake_cluster,
    )

    event_id = _insert_incident(
        event_type="on_error",
        source="fhd",
        payload={"summary": "smoke test incident", "scope": "fhd"},
    )

    result = orchestrate_incident(event_id)

    # 主路径断言
    assert result["ok"] is True
    assert result["event_id"] == event_id
    assert result["scope"] in KNOWN_SCOPES
    assert result["scope"] == "fhd"
    assert 0 <= result["priority"] <= 100
    assert result["should_dispatch"] is True
    assert result["schema_version"] == 1
    assert result["source"] == "phase_d_unified_orchestrator"
    assert "ts" in result
    assert set(result["coverage_scopes"]) == set(KNOWN_SCOPES)

    # resource_plan 来自 mock 的 cluster_status
    rp = result["resource_plan"]
    assert rp["cluster"] == fake_cluster
    assert rp["leader"] == {"node_id": "node-1", "priority": 10}
    assert rp["worker_pool"] == "backend_pool"

    # model_route 由 incident_model_router 正常返回
    mr = result["model_route"]
    assert isinstance(mr, dict)
    assert "model" in mr and "provider" in mr

    # 验证 plan 已持久化回 payload_json
    sf = models.get_session_factory()
    with sf() as s:
        ev = s.query(models.IncidentEvent).filter_by(id=event_id).first()
        persisted = json.loads(ev.payload_json)
        assert persisted["priority"] == result["priority"]
        assert persisted["scope"] == result["scope"]
        assert persisted["_unified_orchestration"]["event_id"] == event_id
        assert persisted["_unified_orchestration"]["schema_version"] == 1


# ---------------------------------------------------------------------------
# 2. scope 别名映射
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_scope,expected",
    [
        ("官网", "website"),
        ("安卓", "android"),
        ("桌面", "desktop"),
        ("管理端", "fhd"),
        ("fhd", "fhd"),
        ("modstore", "modstore"),
        ("website", "website"),
        ("FHD", "fhd"),  # 大小写不敏感
        ("Website", "website"),
    ],
)
def test_scope_alias_mapping(raw_scope, expected):
    """中文别名 / 大小写变体映射到 KNOWN_SCOPES 内的英文标识。"""
    payload = {"scope": raw_scope}
    result = _scope(payload, "")
    assert result == expected, f"scope '{raw_scope}' 应映射到 '{expected}'，实际 '{result}'"
    assert result in KNOWN_SCOPES


def test_scope_uses_source_when_payload_missing():
    """payload 无 scope 时回退到 source 参数。"""
    assert _scope({}, "fhd") == "fhd"
    assert _scope({}, "安卓") == "android"
    assert _scope({}, "官网") == "website"


def test_scope_falls_back_to_global_for_unknown():
    """未知 scope 值回退到 'global'（不在 KNOWN_SCOPES 中）。"""
    payload = {"scope": "unknown-scope-xyz"}
    result = _scope(payload, "")
    assert result == "global"
    assert result not in KNOWN_SCOPES


# ---------------------------------------------------------------------------
# 3. priority 计算边界
# ---------------------------------------------------------------------------


def test_priority_security_token_adds_25():
    """security/secret/credential/payment/auth/安全/支付 token 加 +25。"""
    # base(60) + 25 (security) + 8 (on_error) + 6 (fhd) = 99
    assert _priority("on_error", {"summary": "security breach"}, "fhd") == 99
    # base(60) + 25 (payment) + 8 (on_error) + 6 (fhd) = 99
    assert _priority("on_error", {"summary": "payment failed"}, "fhd") == 99
    # base(60) + 25 (auth) + 8 (on_error) + 6 (fhd) = 99
    assert _priority("on_error", {"summary": "auth token leaked"}, "fhd") == 99
    # base(60) + 25 (支付) + 8 (on_error) + 6 (fhd) = 99
    assert _priority("on_error", {"summary": "支付异常"}, "fhd") == 99
    # secret / credential / 安全
    assert _priority("on_error", {"summary": "secret leaked"}, "fhd") == 99
    assert _priority("on_error", {"summary": "credential exposed"}, "fhd") == 99
    assert _priority("on_error", {"summary": "安全告警"}, "fhd") == 99


def test_priority_outage_token_adds_18():
    """down/outage/500/crash/slo/不可用/宕机 token 加 +18。"""
    # base(60) + 18 (down) + 8 (on_error) + 7 (website) = 93
    p = _priority("on_error", {"summary": "service down outage 500"}, "website")
    assert p == 93
    # 宕机（中文）
    # base(60) + 18 (宕机) + 8 (on_error) + 7 (website) = 93
    assert _priority("on_error", {"summary": "服务宕机"}, "website") == 93


def test_priority_within_bounds():
    """priority 必须始终在 [0, 100] 范围内。"""
    # 极高 base + 所有触发 token → 钳制到 100
    p_high = _priority(
        "on_error",
        {"priority": 200, "summary": "security payment down crash"},
        "android",
    )
    assert p_high == 100

    # base=0，无触发 token
    p_low = _priority("normal", {"priority": 0}, "global")
    assert 0 <= p_low <= 100
    assert p_low == 5  # 0 + 5 (global weight)

    # 负 base → 钳制到 0
    p_neg = _priority("normal", {"priority": -50}, "global")
    assert p_neg == 0  # max(0, -50+5) = 0


def test_priority_invalid_priority_field_falls_back_to_60():
    """payload.priority 非法时回退到 base 60。"""
    # 字符串 priority → ValueError → base=60
    # base(60) + 8 (on_error) + 6 (fhd) = 74
    assert _priority("on_error", {"priority": "not-a-number"}, "fhd") == 74
    # None priority → 回退到 base=60
    assert _priority("on_error", {"priority": None}, "fhd") == 74


def test_priority_scope_weights():
    """不同 scope 的 weight 正确叠加。"""
    # base(60) + 8 (on_error) + scope_weight
    assert _priority("on_error", {}, "android") == 60 + 8 + 8  # 76
    assert _priority("on_error", {}, "desktop") == 60 + 8 + 8  # 76
    assert _priority("on_error", {}, "website") == 60 + 8 + 7  # 75
    assert _priority("on_error", {}, "fhd") == 60 + 8 + 6  # 74
    assert _priority("on_error", {}, "modstore") == 60 + 8 + 6  # 74
    assert _priority("on_error", {}, "global") == 60 + 8 + 5  # 73
    # 未知 scope → 默认 weight 5
    assert _priority("on_error", {}, "unknown") == 60 + 8 + 5  # 73


# ---------------------------------------------------------------------------
# 4. resource_plan mock
# ---------------------------------------------------------------------------


def test_resource_plan_with_mocked_cluster_status(monkeypatch):
    """_resource_plan 使用 mock 的 cluster_status，返回预期结构。"""
    fake_cluster = {
        "ok": True,
        "leader": {"node_id": "leader-1", "priority": 1},
        "active_nodes": [{"node_id": "leader-1"}],
        "stale_nodes": [],
        "backend": "redis",
    }
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: fake_cluster,
    )

    plan = _resource_plan("android", 95, {"requires_device": True})
    assert plan["cluster"] == fake_cluster
    assert plan["leader"] == {"node_id": "leader-1", "priority": 1}
    # priority>=90 → exclusive，但 android/device → device_exclusive
    assert plan["resource_class"] == "device_exclusive"
    assert plan["worker_pool"] == "device_pool"


def test_resource_plan_high_priority_exclusive(monkeypatch):
    """priority >= 90 且无 device 要求 → resource_class = exclusive。"""
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )
    plan = _resource_plan("fhd", 95, {})
    assert plan["resource_class"] == "exclusive"
    assert plan["worker_pool"] == "backend_pool"
    assert plan["leader"] is None


def test_resource_plan_normal_priority(monkeypatch):
    """priority < 90 且无 device → resource_class = normal。"""
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )
    plan = _resource_plan("website", 60, {})
    assert plan["resource_class"] == "normal"
    assert plan["worker_pool"] == "web_pool"


def test_resource_plan_handles_cluster_status_error(monkeypatch):
    """cluster_status 抛异常时 _resource_plan 不应抛错。"""
    def boom(**kw):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("modstore_server.node_coordinator.cluster_status", boom)

    plan = _resource_plan("fhd", 60, {})
    assert plan["cluster"]["ok"] is False
    assert "redis unavailable" in plan["cluster"]["error"]
    assert plan["leader"] is None
    # worker_pool 仍按 scope 映射
    assert plan["worker_pool"] == "backend_pool"


def test_resource_plan_worker_pool_mapping(monkeypatch):
    """各 scope 的 worker_pool 映射正确。"""
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )
    assert _resource_plan("android", 50, {})["worker_pool"] == "device_pool"
    assert _resource_plan("desktop", 50, {})["worker_pool"] == "desktop_pool"
    assert _resource_plan("fhd", 50, {})["worker_pool"] == "backend_pool"
    assert _resource_plan("modstore", 50, {})["worker_pool"] == "backend_pool"
    assert _resource_plan("website", 50, {})["worker_pool"] == "web_pool"
    # 未知 scope → general_pool
    assert _resource_plan("unknown", 50, {})["worker_pool"] == "general_pool"


# ---------------------------------------------------------------------------
# 5. 未知 scope 容错
# ---------------------------------------------------------------------------


def test_orchestrate_incident_unknown_scope_does_not_raise(fresh_db, monkeypatch):
    """payload 中含未知 scope 时 orchestrate_incident 不抛错，回退到 'global'。"""
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )

    event_id = _insert_incident(
        event_type="on_error",
        source="unknown-source",
        payload={"scope": "unknown-scope-xyz", "summary": "weird incident"},
    )

    result = orchestrate_incident(event_id)
    assert result["ok"] is True
    assert result["scope"] == "global"
    assert result["scope"] not in KNOWN_SCOPES
    assert 0 <= result["priority"] <= 100


def test_orchestrate_incident_incident_not_found(fresh_db):
    """不存在的 event_id 返回 ok=False + incident_not_found。"""
    result = orchestrate_incident(999999)
    assert result == {"ok": False, "reason": "incident_not_found"}


def test_orchestrate_incident_invalid_payload_json_does_not_raise(fresh_db, monkeypatch):
    """payload_json 非法 JSON 时回退到 {}，不抛错。"""
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )

    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="fhd",
            payload_json="not-valid-json{",
        )
        s.add(ev)
        s.commit()
        event_id = ev.id

    result = orchestrate_incident(event_id)
    assert result["ok"] is True
    assert result["scope"] in KNOWN_SCOPES or result["scope"] == "global"


# ---------------------------------------------------------------------------
# 6. 重复 event_id 幂等
# ---------------------------------------------------------------------------


def test_orchestrate_incident_idempotent_on_recall(fresh_db, monkeypatch):
    """同一 event_id 调用 2 次，第二次不抛错、不产生半成品状态。

    说明：orchestrate_incident 无显式去重逻辑——每次都重新计算 plan 并覆盖 payload_json。
    注意它会把计算出的 priority 写回 payload，因此第二次调用的 base 会变成第一次的 priority，
    导致 priority 数值递增（反馈循环）。本用例验证：
    1. 两次调用都返回 ok=True（不抛错）
    2. scope 保持确定性（不随 payload.priority 反馈变化）
    3. 第二次调用后 payload_json 仍是合法 JSON 且包含 _unified_orchestration
    4. priority 始终在 [0, 100] 范围内
    """
    monkeypatch.setattr(
        "modstore_server.node_coordinator.cluster_status",
        lambda **kw: {"ok": True, "leader": None},
    )

    event_id = _insert_incident(
        event_type="on_error",
        source="fhd",
        payload={"summary": "idempotency check"},
    )

    result1 = orchestrate_incident(event_id)
    assert result1["ok"] is True
    assert 0 <= result1["priority"] <= 100

    result2 = orchestrate_incident(event_id)
    assert result2["ok"] is True
    assert 0 <= result2["priority"] <= 100

    # scope 来自 payload["scope"] 或 source，不随 priority 反馈变化 → 确定性
    assert result1["scope"] == result2["scope"]
    assert result1["event_id"] == result2["event_id"] == event_id

    # 第二次调用后 payload_json 仍可被正确解析，且 plan 已持久化
    sf = models.get_session_factory()
    with sf() as s:
        ev = s.query(models.IncidentEvent).filter_by(id=event_id).first()
        persisted = json.loads(ev.payload_json)
        assert persisted["_unified_orchestration"]["event_id"] == event_id
        assert persisted["priority"] == result2["priority"]
        assert persisted["scope"] == result2["scope"]
