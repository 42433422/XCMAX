"""Tests for app.neuro_bus.routing.policy_nn — branch coverage ramp.

Covers all functions and key branches in policy_nn.py:
- load_active_policy: torch missing / no manifest / read error / empty policies /
  no matching version / weights not found / torch.load error / success / env override /
  default path / cuda available / None active_version / None policies
- get_policy: caching behavior / returns existing without loading
- predict_action_index: no policy / no mask / partial mask / wrong-length mask / all-True mask
- predict_with_confidence: no policy / no mask / all-masked / partial mask
- save_policy_state_dict: torch missing / success / creates parent dir
- RoutingMLP: init creates net / forward calls net
- _manifest_path: returns correct location
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.routing import policy_nn
from app.neuro_bus.routing.policy_nn import (
    FEATURE_DIM,
    RoutingMLP,
    _manifest_path,
    get_policy,
    load_active_policy,
    predict_action_index,
    predict_with_confidence,
    save_policy_state_dict,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_policy_globals(monkeypatch):
    """Reset module-level _policy and _policy_device before each test."""
    monkeypatch.setattr(policy_nn, "_policy", None)
    monkeypatch.setattr(policy_nn, "_policy_device", "cpu")
    monkeypatch.delenv("XCAGI_ROUTING_POLICY_VERSION", raising=False)


@pytest.fixture
def mock_torch_nn():
    """Inject fake torch and nn modules into policy_nn for the duration of the test."""
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False
    fake_torch.float32 = "float32"
    fake_nn = MagicMock()
    with patch.object(policy_nn, "torch", fake_torch), patch.object(policy_nn, "nn", fake_nn):
        yield fake_torch, fake_nn


def _write_manifest(path: Path, data: dict) -> None:
    """Write a manifest JSON file to the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_loadable_policy_bundle(
    root: Path,
    *,
    active_version: str | None = "0",
    versions: tuple[str, ...] = ("0",),
    omit_path: bool = False,
) -> Path:
    """Create a self-contained manifest plus placeholder policy artifacts."""
    policies = []
    for version in versions:
        relative_path = f"policy_v{version}.pt"
        (root / relative_path).touch()
        policy = {"version": version}
        if not omit_path:
            policy["path"] = relative_path
        policies.append(policy)
    manifest = root / "manifest.json"
    payload = {"policies": policies}
    if active_version is not None:
        payload["active_version"] = active_version
    _write_manifest(manifest, payload)
    return manifest


# ---------------------------------------------------------------------------
# _manifest_path
# ---------------------------------------------------------------------------


class TestManifestPath:
    def test_returns_path_to_routing_policies_manifest(self):
        path = _manifest_path()
        assert path.name == "manifest.json"
        assert "routing_policies" in path.parts
        assert "resources" in path.parts


# ---------------------------------------------------------------------------
# Degradation paths (torch is None — no mocking)
# ---------------------------------------------------------------------------


class TestDegradationPaths:
    def test_load_active_policy_returns_none_when_torch_missing(self, reset_policy_globals):
        assert load_active_policy() is None

    def test_get_policy_returns_none_when_torch_missing(self, reset_policy_globals):
        assert get_policy() is None

    def test_predict_action_index_returns_minus1_when_no_policy(self, reset_policy_globals):
        assert predict_action_index([0.1] * FEATURE_DIM) == -1

    def test_predict_action_index_returns_minus1_with_mask_when_no_policy(
        self, reset_policy_globals
    ):
        assert predict_action_index([0.1] * FEATURE_DIM, mask=[True, False, True]) == -1

    def test_predict_with_confidence_returns_default_when_no_policy(self, reset_policy_globals):
        idx, conf = predict_with_confidence([0.1] * FEATURE_DIM)
        assert idx == -1
        assert conf == 0.0

    def test_predict_with_confidence_returns_default_with_mask_when_no_policy(
        self, reset_policy_globals
    ):
        idx, conf = predict_with_confidence([0.1] * FEATURE_DIM, mask=[False, False, False])
        assert idx == -1
        assert conf == 0.0

    def test_save_policy_state_dict_raises_when_torch_missing(self, tmp_path):
        model = MagicMock()
        with pytest.raises(RuntimeError, match="torch not installed"):
            save_policy_state_dict(tmp_path / "policy.pt", model)


# ---------------------------------------------------------------------------
# load_active_policy (with mocked torch/nn)
# ---------------------------------------------------------------------------


class TestLoadActivePolicy:
    def test_returns_none_when_manifest_file_missing(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        nonexistent = tmp_path / "nonexistent_manifest.json"
        with patch.object(policy_nn, "_manifest_path", return_value=nonexistent):
            assert load_active_policy() is None

    def test_returns_none_when_manifest_read_error(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        bad_manifest = tmp_path / "bad_manifest.json"
        bad_manifest.write_text("{invalid json", encoding="utf-8")
        with patch.object(policy_nn, "_manifest_path", return_value=bad_manifest):
            assert load_active_policy() is None

    def test_returns_none_when_policies_list_empty(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"active_version": "0", "policies": []})
        with patch.object(policy_nn, "_manifest_path", return_value=manifest):
            assert load_active_policy() is None

    def test_returns_none_when_no_matching_version(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        manifest = tmp_path / "manifest.json"
        _write_manifest(
            manifest,
            {"active_version": "99", "policies": [{"version": "0", "path": "policy_v0.pt"}]},
        )
        with patch.object(policy_nn, "_manifest_path", return_value=manifest):
            assert load_active_policy() is None

    def test_returns_none_when_weights_file_not_found(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        manifest = tmp_path / "manifest.json"
        _write_manifest(
            manifest,
            {
                "active_version": "0",
                "policies": [{"version": "0", "path": "nonexistent_weights.pt"}],
            },
        )
        with patch.object(policy_nn, "_manifest_path", return_value=manifest):
            assert load_active_policy() is None

    def test_returns_none_when_torch_load_raises(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        fake_torch, _ = mock_torch_nn
        fake_torch.load.side_effect = RuntimeError("load failed")
        mock_model = MagicMock()
        manifest = _write_loadable_policy_bundle(tmp_path)
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            assert load_active_policy() is None
        fake_torch.load.assert_called_once_with(tmp_path / "policy_v0.pt", map_location="cpu")

    def test_loads_policy_successfully_from_manifest_bundle(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        fake_torch, _ = mock_torch_nn
        mock_model = MagicMock()
        manifest = _write_loadable_policy_bundle(tmp_path, active_version="2", versions=("2",))
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            result = load_active_policy()
        assert result is mock_model
        fake_torch.load.assert_called_once_with(tmp_path / "policy_v2.pt", map_location="cpu")
        mock_model.load_state_dict.assert_called_once()
        mock_model.eval.assert_called_once()
        mock_model.to.assert_called_once_with("cpu")
        assert policy_nn._policy is mock_model
        assert policy_nn._policy_device == "cpu"

    def test_env_override_changes_active_version(
        self, mock_torch_nn, reset_policy_globals, monkeypatch, tmp_path
    ):
        fake_torch, _ = mock_torch_nn
        monkeypatch.setenv("XCAGI_ROUTING_POLICY_VERSION", "0")
        mock_model = MagicMock()
        manifest = _write_loadable_policy_bundle(tmp_path, active_version="2", versions=("0", "2"))
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            result = load_active_policy()
        assert result is mock_model
        call_args = fake_torch.load.call_args
        weights_arg = call_args.args[0] if call_args.args else call_args[0][0]
        assert str(weights_arg).endswith("policy_v0.pt")

    def test_default_path_used_when_policy_has_no_path(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        fake_torch, _ = mock_torch_nn
        manifest = _write_loadable_policy_bundle(tmp_path, omit_path=True)
        mock_model = MagicMock()
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            result = load_active_policy()
        assert result is mock_model
        call_args = fake_torch.load.call_args
        weights_arg = call_args.args[0] if call_args.args else call_args[0][0]
        assert str(weights_arg).endswith("policy_v0.pt")

    def test_cuda_device_used_when_available(self, mock_torch_nn, reset_policy_globals, tmp_path):
        fake_torch, _ = mock_torch_nn
        fake_torch.cuda.is_available.return_value = True
        mock_model = MagicMock()
        manifest = _write_loadable_policy_bundle(tmp_path)
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            result = load_active_policy()
        assert result is mock_model
        assert policy_nn._policy_device == "cuda"
        mock_model.to.assert_called_once_with("cuda")

    def test_active_version_defaults_to_zero_when_none(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        manifest = _write_loadable_policy_bundle(tmp_path, active_version=None)
        mock_model = MagicMock()
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model),
        ):
            result = load_active_policy()
        assert result is mock_model

    def test_policies_none_treated_as_empty(self, mock_torch_nn, reset_policy_globals, tmp_path):
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"active_version": "0", "policies": None})
        with patch.object(policy_nn, "_manifest_path", return_value=manifest):
            assert load_active_policy() is None


# ---------------------------------------------------------------------------
# get_policy (caching)
# ---------------------------------------------------------------------------


class TestGetPolicy:
    def test_caches_loaded_policy_on_second_call(
        self, mock_torch_nn, reset_policy_globals, tmp_path
    ):
        mock_model = MagicMock()
        manifest = _write_loadable_policy_bundle(tmp_path)
        with (
            patch.object(policy_nn, "_manifest_path", return_value=manifest),
            patch.object(policy_nn, "RoutingMLP", return_value=mock_model) as mock_mlp,
        ):
            result1 = get_policy()
            result2 = get_policy()
        assert result1 is mock_model
        assert result2 is mock_model
        mock_mlp.assert_called_once()

    def test_returns_existing_policy_without_loading(self, mock_torch_nn, monkeypatch):
        existing = MagicMock()
        monkeypatch.setattr(policy_nn, "_policy", existing)
        with patch.object(policy_nn, "load_active_policy") as mock_load:
            result = get_policy()
        assert result is existing
        mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# predict_action_index (with mocked policy)
# ---------------------------------------------------------------------------


class TestPredictActionIndex:
    def test_returns_argmax_without_mask(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.argmax.return_value.item.return_value = 2
        policy_nn._policy = MagicMock()
        result = predict_action_index([0.1] * FEATURE_DIM)
        assert result == 2
        fake_torch.tensor.assert_called_once()
        fake_torch.no_grad.assert_called_once()

    def test_applies_partial_mask(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.argmax.return_value.item.return_value = 1
        policy_nn._policy = MagicMock()
        result = predict_action_index([0.1] * FEATURE_DIM, mask=[True, False, True])
        assert result == 1

    def test_ignores_wrong_length_mask(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.argmax.return_value.item.return_value = 0
        policy_nn._policy = MagicMock()
        result = predict_action_index([0.1] * FEATURE_DIM, mask=[True, False])
        assert result == 0

    def test_all_true_mask_does_nothing(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.argmax.return_value.item.return_value = 1
        policy_nn._policy = MagicMock()
        result = predict_action_index([0.1] * FEATURE_DIM, mask=[True, True, True])
        assert result == 1


# ---------------------------------------------------------------------------
# predict_with_confidence (with mocked policy)
# ---------------------------------------------------------------------------


class TestPredictWithConfidence:
    def test_returns_idx_and_confidence_without_mask(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.isinf.return_value.all.return_value.item.return_value = 0
        fake_torch.argmax.return_value.item.return_value = 1
        mock_probs_item = MagicMock()
        mock_probs_item.item.return_value = 0.85
        fake_torch.softmax.return_value.__getitem__.return_value = mock_probs_item
        policy_nn._policy = MagicMock()

        idx, conf = predict_with_confidence([0.1] * FEATURE_DIM)
        assert idx == 1
        assert conf == 0.85

    def test_returns_negative_when_all_masked(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.isinf.return_value.all.return_value.item.return_value = 1
        policy_nn._policy = MagicMock()

        idx, conf = predict_with_confidence([0.1] * FEATURE_DIM, mask=[False, False, False])
        assert idx == -1
        assert conf == 0.0

    def test_applies_partial_mask(self, mock_torch_nn, reset_policy_globals):
        fake_torch, _ = mock_torch_nn
        fake_torch.isinf.return_value.all.return_value.item.return_value = 0
        fake_torch.argmax.return_value.item.return_value = 0
        mock_probs_item = MagicMock()
        mock_probs_item.item.return_value = 0.92
        fake_torch.softmax.return_value.__getitem__.return_value = mock_probs_item
        policy_nn._policy = MagicMock()

        idx, conf = predict_with_confidence([0.1] * FEATURE_DIM, mask=[True, False, True])
        assert idx == 0
        assert conf == 0.92


# ---------------------------------------------------------------------------
# save_policy_state_dict
# ---------------------------------------------------------------------------


class TestSavePolicyStateDict:
    def test_raises_when_torch_missing(self, tmp_path):
        model = MagicMock()
        with pytest.raises(RuntimeError, match="torch not installed"):
            save_policy_state_dict(tmp_path / "policy.pt", model)

    def test_saves_state_dict_and_creates_parent(self, mock_torch_nn, tmp_path):
        fake_torch, _ = mock_torch_nn
        model = MagicMock()
        state = {"weights": "data"}
        model.state_dict.return_value = state
        save_path = tmp_path / "subdir" / "policy.pt"

        save_policy_state_dict(save_path, model)

        fake_torch.save.assert_called_once_with(state, save_path)
        assert save_path.parent.is_dir()


# ---------------------------------------------------------------------------
# RoutingMLP
# ---------------------------------------------------------------------------


class TestRoutingMLP:
    def test_init_creates_sequential_net(self, mock_torch_nn):
        _, fake_nn = mock_torch_nn
        model = RoutingMLP()
        fake_nn.Sequential.assert_called_once()
        assert model.net is fake_nn.Sequential.return_value

    def test_forward_calls_net(self, mock_torch_nn):
        _, fake_nn = mock_torch_nn
        model = RoutingMLP()
        x = MagicMock()
        result = model.forward(x)
        model.net.assert_called_once_with(x)
        assert result is model.net.return_value
