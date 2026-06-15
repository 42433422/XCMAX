"""app/domain/services/unified_intent_recognizer 单测（mock 子引擎，不加载真实模型）。"""

from __future__ import annotations

import pytest

from app.domain.services import unified_intent_recognizer as uir_mod
from app.domain.services.unified_intent_recognizer import UnifiedIntentRecognizer


@pytest.fixture()
def recognizer() -> UnifiedIntentRecognizer:
    r = UnifiedIntentRecognizer()
    r._initialized = True
    return r


class TestRecognizeEmpty:
    def test_blank_returns_unk(self, recognizer: UnifiedIntentRecognizer):
        assert recognizer.recognize("") == {
            "intent": "unk",
            "confidence": 0.0,
            "source": "unified",
        }
        assert recognizer.recognize("   ")["intent"] == "unk"


class TestRecognizeUncached:
    def test_distilled_high_confidence(self, recognizer: UnifiedIntentRecognizer):
        class Distilled:
            def predict(self, text: str):
                return {"intent": "order", "confidence": 0.9}

        recognizer.distilled_recognizer = Distilled()
        out = recognizer._recognize_uncached("下单")
        assert out["intent"] == "order"
        assert out["source"] == "distilled"

    def test_bert_when_distilled_low(self, recognizer: UnifiedIntentRecognizer):
        class Low:
            def predict(self, text: str):
                return {"intent": "x", "confidence": 0.1}

        class Bert:
            def predict(self, text: str):
                return {"intent": "product", "confidence": 0.85}

        recognizer.distilled_recognizer = Low()
        recognizer.bert_recognizer = Bert()
        out = recognizer._recognize_uncached("查产品")
        assert out["source"] == "bert"

    def test_rasa_branch(self, recognizer: UnifiedIntentRecognizer, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "1")

        class Rasa:
            confidence_threshold = 0.6

            def parse(self, text: str):
                return {"intent": {"name": "greet", "confidence": 0.8}, "entities": []}

        recognizer.distilled_recognizer = None
        recognizer.bert_recognizer = None
        recognizer.rasa_recognizer = Rasa()
        out = recognizer._recognize_uncached("你好")
        assert out["intent"] == "greet"
        assert out["source"] == "rasa"

    def test_deepseek_fallback(self, recognizer: UnifiedIntentRecognizer):
        class Deep:
            def recognize(self, text: str):
                return {"intent": "chat", "confidence": 0.95}

        recognizer.distilled_recognizer = None
        recognizer.bert_recognizer = None
        recognizer.rasa_recognizer = None
        recognizer.deepseek_recognizer = Deep()
        out = recognizer._recognize_uncached("聊聊")
        assert out["intent"] == "chat"
        assert out["source"] == "deepseek"

    def test_all_miss_returns_unk(self, recognizer: UnifiedIntentRecognizer):
        recognizer.distilled_recognizer = None
        recognizer.bert_recognizer = None
        recognizer.rasa_recognizer = None
        recognizer.deepseek_recognizer = None
        assert recognizer._recognize_uncached("x")["intent"] == "unk"


class TestStatus:
    def test_is_ready_when_initialized(self, recognizer: UnifiedIntentRecognizer):
        assert recognizer.is_ready() is True

    def test_engine_status_shape(self, recognizer: UnifiedIntentRecognizer):
        status = recognizer.get_engine_status()
        assert "rule" in status and status["rule"]["loaded"] is True
        assert "bert" in status


class TestEnvFlag:
    def test_truthy_values(self, monkeypatch):
        monkeypatch.setenv("X_FLAG", "yes")
        assert uir_mod._env_flag("X_FLAG") is True

    def test_falsey(self, monkeypatch):
        monkeypatch.setenv("X_FLAG", "0")
        assert uir_mod._env_flag("X_FLAG") is False
