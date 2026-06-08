from pathlib import Path

import pytest

from app.neuro_bus.routing.features import build_routing_features
from app.neuro_bus.routing.policy_nn import FEATURE_DIM, load_active_policy, predict_action_index


def test_feature_vector_length():
    v = build_routing_features("打印出货单", event=None, extra={"intent_confidence": 0.9})
    assert len(v) == FEATURE_DIM


def test_policy_predict_if_weights_present():
    """Requires resources/routing_policies/policy_v0.pt from train script --init-only."""
    p = Path(__file__).resolve().parents[2] / "resources" / "routing_policies" / "policy_v0.pt"
    if not p.is_file():
        pytest.skip("policy_v0.pt not present")
    load_active_policy()
    idx = predict_action_index([0.1] * FEATURE_DIM)
    assert 0 <= idx < 3
