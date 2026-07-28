"""Regression tests for packaged routing-policy persistence boundaries."""

from __future__ import annotations

import sys
from pathlib import Path

from app.neuro_bus.routing import online_learner, policy_nn


def test_packaged_policy_writes_use_user_data_not_bundle(tmp_path, monkeypatch) -> None:
    user_data = tmp_path / "userData"
    bundle = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend" / "_internal"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(policy_nn, "get_app_data_dir", lambda: str(user_data))

    expected = user_data / "models" / "routing_policies"

    assert policy_nn.policy_write_dir() == expected
    assert policy_nn.policy_manifest_write_path() == expected / "manifest.json"
    assert online_learner._policies_dir() == expected
    assert online_learner._manifest_path() == expected / "manifest.json"
    assert not expected.is_relative_to(bundle)


def test_packaged_policy_loader_prefers_learned_user_data_manifest(tmp_path, monkeypatch) -> None:
    user_data = tmp_path / "userData"
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setattr(policy_nn, "get_app_data_dir", lambda: str(user_data))
    learned_manifest = user_data / "models" / "routing_policies" / "manifest.json"
    learned_manifest.parent.mkdir(parents=True)
    learned_manifest.write_text('{"active_version":"1","policies":[]}', encoding="utf-8")

    assert policy_nn._manifest_path() == learned_manifest
