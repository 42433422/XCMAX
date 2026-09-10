"""跨仓一致性：FHD 状态机 vs 市场端共享核心（work_order_core）不得漂移。

共享模式上线后，FHD 侧把工单读写/判定委托市场端；本测试锁死两侧
wo_id 派生、轨道分类、状态迁移三条规则的输出必须一致，防双实现漂移。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.services import work_order_ssot as fhd

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODSTORE_CORE = (
    _REPO_ROOT
    / "成都修茈科技有限公司"
    / "MODstore_deploy"
    / "modstore_server"
    / "work_order_core.py"
)


def _load_server_core():
    if not _MODSTORE_CORE.exists():  # pragma: no cover - checkout 缺 modstore 时跳过
        return None
    spec = importlib.util.spec_from_file_location("server_work_order_core", _MODSTORE_CORE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["server_work_order_core"] = module
    spec.loader.exec_module(module)
    return module


server = _load_server_core()


class TestWoidParity:
    def test_derive_wo_id_identical(self) -> None:
        if server is None:
            return
        for key in ("k", "abc123", "x"):
            assert fhd.derive_wo_id(key) == server.derive_wo_id(key)


class TestClassifyTrackParity:
    def test_matching_matrix(self) -> None:
        if server is None:
            return
        samples = [
            {},
            {"reason": "intent_unknown"},
            {"reason": "llm_timeout"},
            {"reason": "install_failed"},
            {"reason": "llm_timeout", "context": {"customer_id": "c-1"}},
            {"context": {"customer_id": "c-1"}},
            {"context": {"account_id": "a-1"}},
            {"context": {"industry": "涂料"}},
            {"context": {"intent_result": {"industry": "考勤"}}},
            {"context": {"skill_proposal": {"customer_scoped": True, "industry": "涂料"}}},
        ]
        for kwargs in samples:
            fhd_track = fhd.classify_track(**kwargs)
            server_track = server.classify_track(**kwargs)
            assert fhd_track == server_track, (kwargs, fhd_track, server_track)


class TestTransitionParity:
    def test_allowed_transitions_identical(self) -> None:
        if server is None:
            return
        states = fhd.WO_STATES
        for current in states:
            for target in states:
                fhd_blocked = (
                    target not in fhd._ALLOWED_TRANSITIONS.get(current, frozenset())
                    and target != current
                )
                server_blocked = server.validate_transition(current, target) not in (
                    "",
                    "already_in_state",
                )
                assert fhd_blocked is server_blocked, (current, target)  # type: ignore[attr-defined]

    def test_state_sets_identical(self) -> None:
        if server is None:
            return
        assert set(fhd.WO_STATES) == set(server.WO_STATES)
        assert set(fhd.WO_TRACKS) == set(server.WO_TRACKS)
        assert frozenset(fhd._OPS_REASONS) == frozenset(server._OPS_REASONS)
