from pathlib import Path

import pytest

from app.neuro_bus.routing.features import build_routing_features
from app.neuro_bus.routing.policy_nn import FEATURE_DIM, predict_action_index


def test_feature_vector_length():
    v = build_routing_features("打印出货单", event=None, extra={"intent_confidence": 0.9})
    assert len(v) == FEATURE_DIM


def test_policy_predict_with_in_memory_model():
    """无需 policy_v0.pt：用内存 MLP 验证 predict_action_index 行为。"""
    import app.neuro_bus.routing.policy_nn as policy_nn

    torch_mod = policy_nn.torch
    if torch_mod is None or not hasattr(torch_mod, "Tensor"):
        pytest.skip("PyTorch not available")

    from app.neuro_bus.routing.policy_nn import RoutingMLP

    model = RoutingMLP()
    policy_nn._policy = model
    policy_nn._policy_device = "cpu"
    idx = predict_action_index([0.1] * FEATURE_DIM)
    assert 0 <= idx < 3
