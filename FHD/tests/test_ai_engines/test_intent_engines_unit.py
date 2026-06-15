"""Phase 2: ai_engines 意图识别单元测试（mock 外部依赖）。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.ai_engines.deepseek.intent_service import (
    INTENT_DESCRIPTIONS,
    SLOT_DEFINITIONS,
    DeepseekIntentClassifier,
    _IntentRecognitionCache,
)
from app.ai_engines.rasa.nlu_service import RasaNLUService, reset_rasa_nlu_service

try:
    from app.ai_engines.bert.intent_service import (
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        BertIntentClassifier,
    )

    _BERT_AVAILABLE = True
except ModuleNotFoundError:
    _BERT_AVAILABLE = False


@pytest.mark.skipif(not _BERT_AVAILABLE, reason="torch/transformers not installed")
class TestBertIntentClassifier:
    def test_label_mappings(self):
        assert len(INTENT_LABELS) == len(LABEL_TO_ID)
        assert ID_TO_LABEL[0] == INTENT_LABELS[0]

    def test_init_defaults(self):
        clf = BertIntentClassifier()
        assert clf.confidence_threshold == 0.7
        assert clf.max_length == 64
        assert clf.device in ("cpu", "cuda")

    def test_predict_empty_text(self):
        clf = BertIntentClassifier()
        clf._initialized = True
        out = clf.predict("   ")
        assert out["intent"] == "unk"
        assert out["confidence"] == 0.0

    def test_predict_batch_delegates(self):
        with patch.object(BertIntentClassifier, "load_model", return_value=False):
            clf = BertIntentClassifier()
            with patch.object(clf, "predict", return_value={"intent": "greet"}) as mock_pred:
                out = clf.predict_batch(["hi", "bye"])
        assert len(out) == 2
        assert mock_pred.call_count == 2


class TestDeepseekIntentCache:
    def test_get_miss(self):
        cache = _IntentRecognitionCache(max_size=10, ttl_seconds=60)
        assert cache.get("hello") is None

    def test_set_and_get_hit(self):
        cache = _IntentRecognitionCache()
        cache.set("Hello", {"intent": "greet", "confidence": 0.9})
        hit = cache.get("  hello  ")
        assert hit is not None
        assert hit["intent"] == "greet"

    def test_ttl_expiry(self):
        cache = _IntentRecognitionCache(ttl_seconds=0)
        cache.set("x", {"intent": "greet"})
        time.sleep(0.01)
        assert cache.get("x") is None

    def test_evicts_oldest_at_capacity(self):
        cache = _IntentRecognitionCache(max_size=2)
        cache.set("a", {"intent": "a"})
        cache.set("b", {"intent": "b"})
        cache.set("c", {"intent": "c"})
        assert cache.get("a") is None
        assert cache.get("c") is not None

    def test_clear(self):
        cache = _IntentRecognitionCache()
        cache.set("a", {"intent": "x"})
        cache.clear()
        assert cache.get("a") is None


class TestDeepseekIntentClassifier:
    def test_constants_nonempty(self):
        assert "shipment_generate" in INTENT_DESCRIPTIONS
        assert "unit_name" in SLOT_DEFINITIONS

    def test_init(self):
        clf = DeepseekIntentClassifier(api_key="k", confidence_threshold=0.6)
        assert clf.api_key == "k"
        assert clf.max_retries == 3

    def test_get_api_key_from_instance(self):
        clf = DeepseekIntentClassifier(api_key="direct")
        assert clf._get_api_key() == "direct"

    def test_load_model_always_true(self):
        assert DeepseekIntentClassifier().load_model() is True

    def test_predict_returns_unk_stub(self):
        out = DeepseekIntentClassifier().predict("hello")
        assert out["intent"] == "unk"
        assert out["source"] == "deepseek"

    @pytest.mark.asyncio
    async def test_recognize_cache_hit(self):
        clf = DeepseekIntentClassifier()
        with patch("app.ai_engines.deepseek.intent_service._intent_recognition_cache") as mock_cache:
            mock_cache.get.return_value = {"intent": "greet", "confidence": 0.99}
            out = await clf.recognize("hi")
        assert out["intent"] == "greet"
        mock_cache.get.assert_called_once_with("hi")

    @pytest.mark.asyncio
    async def test_recognize_api_failure_returns_unk(self):
        clf = DeepseekIntentClassifier(api_key="k", max_retries=1)
        with patch("app.ai_engines.deepseek.intent_service._intent_recognition_cache") as mock_cache:
            mock_cache.get.return_value = None
            with patch(
                "app.infrastructure.llm.invoke.chat_completion_openai_format",
                side_effect=RuntimeError("api down"),
            ):
                out = await clf.recognize("开单")
        assert out["intent"] == "unk"
        assert out["confidence"] == 0.0


class TestRasaNLUService:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        reset_rasa_nlu_service()
        yield
        reset_rasa_nlu_service()

    def test_disabled_returns_empty(self):
        svc = RasaNLUService(enabled=False)
        out = svc.parse("hello")
        assert out["intent"]["name"] is None
        assert out["message"] == "disabled"

    def test_empty_text(self):
        svc = RasaNLUService(enabled=True, use_server=False)
        out = svc.parse("  ")
        assert out["message"] == "empty_text"

    def test_get_status_without_load(self):
        svc = RasaNLUService(enabled=True, model_path="/nonexistent/model.tar.gz")
        status = svc.get_status()
        assert status["enabled"] is True
        assert status["agent_loaded"] is False

    def test_is_available_disabled(self):
        assert RasaNLUService(enabled=False).is_available() is False

    @patch("requests.get")
    def test_is_available_server_mode(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        svc = RasaNLUService(enabled=True, use_server=True, rasa_url="http://localhost:5005")
        assert svc.is_available() is True

    @patch("requests.post")
    def test_parse_via_server_success(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "intent": {"name": "greet", "confidence": 0.9},
            "entities": [],
        }
        mock_post.return_value = mock_resp
        svc = RasaNLUService(enabled=True, use_server=True)
        out = svc.parse("你好")
        assert out["intent"]["name"] == "greet"

    @pytest.mark.asyncio
    async def test_parse_async(self):
        svc = RasaNLUService(enabled=False)
        out = await svc.parse_async("x")
        assert out["message"] == "disabled"

    def test_get_intent_with_confidence(self):
        svc = RasaNLUService(enabled=False)
        name, conf = svc.get_intent_with_confidence("x")
        assert name is None
        assert conf == 0.0
