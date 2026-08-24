from __future__ import annotations

import sys
from pathlib import Path

from app.domain.neuro.cognition import plan_constraints, plan_graph_log
from app.domain.neuro.evolution import self_reflection
from app.neuro_bus.routing import online_learner, policy_nn, routing_log
from app.utils.path_io.ai_runtime_artifacts import (
    mutable_ai_artifact_path,
    readable_ai_artifact_path,
)


def test_desktop_runtime_artifacts_never_target_bundle(tmp_path, monkeypatch):
    data_root = tmp_path / "user-data"
    source = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "seed.jsonl"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_root))
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)

    result = mutable_ai_artifact_path("routing_policies/events.jsonl", source_fallback=source)

    assert result == data_root / "data" / "ai_runtime" / "routing_policies" / "events.jsonl"
    assert "XCAGI.app" not in str(result)


def test_readable_runtime_artifact_falls_back_then_prefers_user_data(tmp_path, monkeypatch):
    data_root = tmp_path / "user-data"
    bundled = tmp_path / "bundle" / "manifest.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_root))

    assert (
        readable_ai_artifact_path("routing_policies/manifest.json", bundled_default=bundled)
        == bundled
    )

    runtime = data_root / "data" / "ai_runtime" / "routing_policies" / "manifest.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("{}", encoding="utf-8")
    assert (
        readable_ai_artifact_path("routing_policies/manifest.json", bundled_default=bundled)
        == runtime
    )


def test_all_mutable_neuro_artifacts_use_user_data(tmp_path, monkeypatch):
    data_root = tmp_path / "user-data"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_root))
    monkeypatch.delenv("XCAGI_PLAN_GRAPH_LOG", raising=False)
    monkeypatch.delenv("XCAGI_ROUTING_LOG_PATH", raising=False)
    monkeypatch.delenv("XCAGI_REFLECTION_LEDGER", raising=False)
    monkeypatch.delenv("XCAGI_SOFT_CONSTRAINTS_PATH", raising=False)

    expected_root = data_root / "data" / "ai_runtime" / "routing_policies"
    assert plan_graph_log._log_path() == expected_root / "plan_graphs.jsonl"
    assert routing_log._default_log_path() == expected_root / "routing_decisions.jsonl"
    assert self_reflection._ledger_path() == expected_root / "reflection_ledger.jsonl"
    assert plan_constraints._writable_constraints_path() == expected_root / "soft_constraints.json"
    assert online_learner._manifest_path(for_write=True) == expected_root / "manifest.json"
    assert online_learner._policies_dir() == expected_root


def test_frozen_runtime_without_launcher_env_still_uses_user_data(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "app.desktop_runtime.paths.get_desktop_data_dir",
        lambda data_dir=None: tmp_path / "frozen-user-data",
    )

    result = mutable_ai_artifact_path(
        "routing_policies/plan_graphs.jsonl",
        source_fallback=Path("/Applications/XCAGI.app/Contents/Resources/plan_graphs.jsonl"),
    )

    assert result == (
        tmp_path
        / "frozen-user-data"
        / "data"
        / "ai_runtime"
        / "routing_policies"
        / "plan_graphs.jsonl"
    )


def test_policy_reader_uses_runtime_manifest_when_present(tmp_path, monkeypatch):
    data_root = tmp_path / "user-data"
    runtime_manifest = data_root / "data" / "ai_runtime" / "routing_policies" / "manifest.json"
    runtime_manifest.parent.mkdir(parents=True)
    runtime_manifest.write_text('{"active_version":"9","policies":[]}', encoding="utf-8")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_root))

    assert policy_nn._manifest_path() == runtime_manifest
