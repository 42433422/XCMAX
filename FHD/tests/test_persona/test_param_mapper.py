"""模型参数映射器测试。"""

from __future__ import annotations

import pytest

from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.param_mapper import PersonaParamMapper


class TestPersonaParamMapper:
    """模型参数映射器测试。"""

    @pytest.fixture
    def mapper(self):
        return PersonaParamMapper()

    def test_map_returns_dict_with_required_keys(self, mapper):
        axes = PersonaAxes()
        params = mapper.map(axes, RapportScore())
        assert "temperature" in params
        assert "max_tokens" in params
        assert "top_p" in params
        assert "frequency_penalty" in params
        assert "presence_penalty" in params

    def test_high_warmth_increases_temperature(self, mapper):
        high = mapper.map(PersonaAxes(warmth=1.0), RapportScore())
        low = mapper.map(PersonaAxes(warmth=0.0), RapportScore())
        assert high["temperature"] > low["temperature"]

    def test_high_detail_increases_max_tokens(self, mapper):
        high = mapper.map(PersonaAxes(detail=1.0), RapportScore())
        low = mapper.map(PersonaAxes(detail=0.0), RapportScore())
        assert high["max_tokens"] > low["max_tokens"]

    def test_high_structure_decreases_top_p(self, mapper):
        high = mapper.map(PersonaAxes(structure=1.0), RapportScore())
        low = mapper.map(PersonaAxes(structure=0.0), RapportScore())
        assert high["top_p"] < low["top_p"]

    def test_high_proactivity_increases_frequency_penalty(self, mapper):
        high = mapper.map(PersonaAxes(proactivity=1.0), RapportScore())
        low = mapper.map(PersonaAxes(proactivity=0.0), RapportScore())
        assert high["frequency_penalty"] > low["frequency_penalty"]

    def test_temperature_in_valid_range(self, mapper):
        axes = PersonaAxes(warmth=0.5)
        params = mapper.map(axes, RapportScore())
        assert 0.0 <= params["temperature"] <= 1.0

    def test_max_tokens_positive(self, mapper):
        axes = PersonaAxes(detail=0.0)
        params = mapper.map(axes, RapportScore())
        assert params["max_tokens"] > 0

    def test_top_p_in_valid_range(self, mapper):
        axes = PersonaAxes(structure=0.5)
        params = mapper.map(axes, RapportScore())
        assert 0.0 < params["top_p"] <= 1.0

    def test_presence_penalty_always_zero(self, mapper):
        axes = PersonaAxes()
        params = mapper.map(axes, RapportScore())
        assert params["presence_penalty"] == 0
