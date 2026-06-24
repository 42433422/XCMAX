"""OnlineLearner 覆盖率补强测试 — update_policy / manifest / sha256 / 路径辅助。

聚焦 online_learner.py 未覆盖分支：
- _manifest_path / _policies_dir 路径构造
- should_explore 的 explore 分支计数
- update_policy: torch缺失 / 空窗口 / 无policy / 成功路径 / 异常路径
- _next_version: 无manifest / 有manifest / 异常降级
- _update_manifest: 新建 / 已有 / 损坏降级 / 幂等去重
- _compute_sha256: 真实文件哈希
"""

from __future__ import annotations

import hashlib
import json

import pytest

import app.neuro_bus.routing.online_learner as ol_mod
from app.neuro_bus.routing.online_learner import OnlineLearner

torch = pytest.importorskip("torch")
from app.neuro_bus.routing.policy_nn import RoutingMLP  # noqa: E402


# ---------------------------------------------------------------------------
# 路径辅助函数
# ---------------------------------------------------------------------------
def test_manifest_path_points_to_routing_policies_manifest():
    p = ol_mod._manifest_path()
    assert p.name == "manifest.json"
    assert p.parent.name == "routing_policies"
    assert p.parent.parent.name == "resources"


def test_policies_dir_points_to_routing_policies():
    d = ol_mod._policies_dir()
    assert d.name == "routing_policies"
    # _manifest_path 应在 _policies_dir 之内
    assert ol_mod._manifest_path().parent == d


# ---------------------------------------------------------------------------
# should_explore explore 分支
# ---------------------------------------------------------------------------
def test_should_explore_increments_explore_count_when_decision_true(monkeypatch):
    """random < epsilon 时走 explore 分支，explore_count 自增。"""
    learner = OnlineLearner(epsilon=0.1)
    monkeypatch.setattr(ol_mod.random, "random", lambda: 0.0)  # 强制 < epsilon
    result = learner.should_explore()
    assert result is True
    assert learner._explore_count == 1
    assert learner._total_count == 1


def test_should_explore_no_increment_when_decision_false(monkeypatch):
    """random >= epsilon 时不探索，explore_count 不变但 total_count 自增。"""
    learner = OnlineLearner(epsilon=0.1)
    monkeypatch.setattr(ol_mod.random, "random", lambda: 0.99)  # >= epsilon
    result = learner.should_explore()
    assert result is False
    assert learner._explore_count == 0
    assert learner._total_count == 1
    # explore_rate 在 stats 中正确反映
    assert learner.get_stats()["explore_rate"] == 0.0


# ---------------------------------------------------------------------------
# update_policy 降级分支
# ---------------------------------------------------------------------------
def test_update_policy_returns_none_when_torch_missing(monkeypatch):
    """torch 不可用时优雅返回 None。"""
    learner = OnlineLearner()
    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)
    monkeypatch.setattr(ol_mod, "torch", None)
    assert learner.update_policy() is None


def test_update_policy_returns_none_when_nn_missing(monkeypatch):
    """nn 不可用时返回 None。"""
    learner = OnlineLearner()
    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)
    monkeypatch.setattr(ol_mod, "nn", None)
    assert learner.update_policy() is None


def test_update_policy_returns_none_on_empty_window():
    """空窗口直接返回 None。"""
    learner = OnlineLearner()
    assert len(learner._window) == 0
    assert learner.update_policy() is None


def test_update_policy_returns_none_when_no_active_policy(monkeypatch):
    """get_policy 返回 None 时返回 None。"""
    learner = OnlineLearner()
    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)
    monkeypatch.setattr(ol_mod, "get_policy", lambda: None)
    assert learner.update_policy() is None


# ---------------------------------------------------------------------------
# update_policy 成功路径
# ---------------------------------------------------------------------------
def test_update_policy_success_returns_version_and_persists(monkeypatch, tmp_path):
    """完整成功路径：训练 → 保存权重 → 写 manifest → 返回新版本号。"""
    policies_dir = tmp_path / "routing_policies"
    policies_dir.mkdir(parents=True)
    manifest_file = policies_dir / "manifest.json"

    # 真实 policy 模型（torch 可用）
    policy = RoutingMLP()

    saved_calls: list = []

    def fake_save(path, model):
        # 真实写一个小文件以便 sha256 能算
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-weights")
        saved_calls.append((path, model))

    monkeypatch.setattr(ol_mod, "get_policy", lambda: policy)
    monkeypatch.setattr(ol_mod, "save_policy_state_dict", fake_save)
    monkeypatch.setattr(ol_mod, "_policies_dir", lambda: policies_dir)
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)

    learner = OnlineLearner(lr=0.01)
    # 多条样本，含不同 action（0..2）以走 gather / softmax / IS 权重逻辑
    for i in range(5):
        learner.record_decision(
            features=[float(i) * 0.1] * 16,
            action=i % 3,
            sla_hit=bool(i % 2),
            success=True,
        )

    version = learner.update_policy()

    # 无既有 manifest → 起始版本 "1"
    assert version == "1"
    # save_policy_state_dict 被调用，路径含版本号
    assert len(saved_calls) == 1
    assert saved_calls[0][0].name == "policy_v1.pt"
    # manifest 已写入且 active_version 指向新版本
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["active_version"] == "1"
    assert manifest["policies"][-1]["version"] == "1"
    assert manifest["policies"][-1]["path"] == "policy_v1.pt"
    assert len(manifest["policies"][-1]["sha256"]) == 64


def test_update_policy_returns_none_on_recoverable_error(monkeypatch):
    """训练中抛 RuntimeError(在 RECOVERABLE_ERRORS 中) → 捕获并返回 None。"""
    learner = OnlineLearner()
    learner.record_decision([0.1] * 16, action=0, sla_hit=True, success=True)

    class BoomPolicy:
        def train(self):
            raise RuntimeError("boom in train")

    monkeypatch.setattr(ol_mod, "get_policy", lambda: BoomPolicy())
    assert learner.update_policy() is None


def test_update_policy_increments_version_with_existing_manifest(monkeypatch, tmp_path):
    """已有 manifest 含版本 3,5 → 新版本应为 6。"""
    policies_dir = tmp_path / "routing_policies"
    policies_dir.mkdir(parents=True)
    manifest_file = policies_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "active_version": "5",
                "policies": [
                    {"version": "3", "path": "policy_v3.pt"},
                    {"version": "5", "path": "policy_v5.pt"},
                ],
            }
        ),
        encoding="utf-8",
    )

    policy = RoutingMLP()

    def fake_save(path, model):
        path.write_bytes(b"w")

    monkeypatch.setattr(ol_mod, "get_policy", lambda: policy)
    monkeypatch.setattr(ol_mod, "save_policy_state_dict", fake_save)
    monkeypatch.setattr(ol_mod, "_policies_dir", lambda: policies_dir)
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)

    learner = OnlineLearner()
    learner.record_decision([0.2] * 16, action=1, sla_hit=True, success=True)

    version = learner.update_policy()
    assert version == "6"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["active_version"] == "6"
    # 旧条目保留 + 新条目追加
    versions = {p["version"] for p in manifest["policies"]}
    assert versions == {"3", "5", "6"}


# ---------------------------------------------------------------------------
# _next_version
# ---------------------------------------------------------------------------
def test_next_version_returns_one_when_no_manifest(monkeypatch, tmp_path):
    missing = tmp_path / "nope" / "manifest.json"
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: missing)
    learner = OnlineLearner()
    assert learner._next_version() == "1"


def test_next_version_reads_max_and_increments(monkeypatch, tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "policies": [
                    {"version": "2"},
                    {"version": "7"},
                    {"version": "abc"},  # 非数字应被忽略
                    {"version": "4"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)
    learner = OnlineLearner()
    assert learner._next_version() == "8"


def test_next_version_no_digit_versions_returns_one(monkeypatch, tmp_path):
    """policies 存在但无数字版本 → max_v=0 → 返回 '1'。"""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps({"policies": [{"version": "x"}, {"version": ""}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)
    learner = OnlineLearner()
    assert learner._next_version() == "1"


def test_next_version_returns_one_on_corrupt_manifest(monkeypatch, tmp_path):
    """损坏 JSON → JSONDecodeError(RECOVERABLE) → 降级返回 '1'。"""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text("{ not valid json ", encoding="utf-8")
    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)
    learner = OnlineLearner()
    assert learner._next_version() == "1"


# ---------------------------------------------------------------------------
# _update_manifest
# ---------------------------------------------------------------------------
def test_update_manifest_creates_new_file(monkeypatch, tmp_path):
    """无既有 manifest → 新建，写入条目与 active_version。"""
    policies_dir = tmp_path / "routing_policies"
    manifest_file = policies_dir / "manifest.json"
    weights = tmp_path / "policy_v1.pt"
    weights.write_bytes(b"hello-weights")

    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)

    learner = OnlineLearner()
    learner._update_manifest("1", weights)

    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["active_version"] == "1"
    assert len(manifest["policies"]) == 1
    entry = manifest["policies"][0]
    assert entry["version"] == "1"
    assert entry["path"] == "policy_v1.pt"
    assert entry["sha256"] == hashlib.sha256(b"hello-weights").hexdigest()
    assert entry["trained_at"].endswith("Z")


def test_update_manifest_idempotent_replaces_same_version(monkeypatch, tmp_path):
    """已有同版本条目 → 被移除后重新追加（幂等，不重复）。"""
    policies_dir = tmp_path / "routing_policies"
    policies_dir.mkdir(parents=True)
    manifest_file = policies_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "active_version": "1",
                "policies": [
                    {"version": "2", "path": "old_v2.pt", "sha256": "stale"},
                ],
            }
        ),
        encoding="utf-8",
    )
    weights = tmp_path / "policy_v2.pt"
    weights.write_bytes(b"new-data")

    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)

    learner = OnlineLearner()
    learner._update_manifest("2", weights)

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    v2_entries = [p for p in manifest["policies"] if p["version"] == "2"]
    assert len(v2_entries) == 1  # 幂等去重
    assert v2_entries[0]["sha256"] == hashlib.sha256(b"new-data").hexdigest()
    assert manifest["active_version"] == "2"


def test_update_manifest_recovers_from_corrupt_manifest(monkeypatch, tmp_path):
    """损坏 JSON 的既有 manifest → 降级为默认空骨架后再写入。"""
    policies_dir = tmp_path / "routing_policies"
    policies_dir.mkdir(parents=True)
    manifest_file = policies_dir / "manifest.json"
    manifest_file.write_text("<<<corrupt>>>", encoding="utf-8")
    weights = tmp_path / "policy_v9.pt"
    weights.write_bytes(b"x")

    monkeypatch.setattr(ol_mod, "_manifest_path", lambda: manifest_file)

    learner = OnlineLearner()
    learner._update_manifest("9", weights)

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["active_version"] == "9"
    assert [p["version"] for p in manifest["policies"]] == ["9"]


# ---------------------------------------------------------------------------
# _compute_sha256
# ---------------------------------------------------------------------------
def test_compute_sha256_matches_hashlib(tmp_path):
    f = tmp_path / "blob.bin"
    payload = b"the quick brown fox" * 1000  # 跨多个 8192 chunk
    f.write_bytes(payload)
    digest = OnlineLearner._compute_sha256(f)
    assert digest == hashlib.sha256(payload).hexdigest()


def test_compute_sha256_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert OnlineLearner._compute_sha256(f) == hashlib.sha256(b"").hexdigest()
