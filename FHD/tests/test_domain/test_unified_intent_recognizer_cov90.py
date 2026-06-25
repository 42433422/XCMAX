"""覆盖 app/domain/services/unified_intent_recognizer 中此前未测的分支。

聚焦：
- ``load()`` 的首选/兼容 import 路径、load_model() 调用、以及各子引擎实例化
  失败时落入 ``except RECOVERABLE_ERRORS`` 并写入 ``_engine_errors``。
- ``recognize()`` 的意图缓存路径：缓存命中 / 缓存为空回退 / 缓存抛错回退。
- ``_recognize_uncached`` 各引擎的预测异常、低置信、RASA 开关关闭、
  DeepSeek 无 predict/recognize 方法、返回非 dict 等分支。
- ``is_ready()`` 的 load 异常、``_rasa_status_snapshot`` 的 get_status 异常。

所有外部依赖（子引擎类、缓存端口、请求上下文）均被 mock，离线、确定、快速。
子引擎类的 ``import`` 发生在 ``load()`` 函数内部，因此通过向 ``sys.modules``
注入假模块来在“使用处”拦截。
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from app.domain.services import unified_intent_recognizer as uir_mod
from app.domain.services.unified_intent_recognizer import UnifiedIntentRecognizer


def _make_module(name: str, **attrs: object) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


@pytest.fixture()
def initialized() -> UnifiedIntentRecognizer:
    """已标记 initialized 的识别器（跳过 load()，直接测 _recognize_uncached/状态）。"""
    r = UnifiedIntentRecognizer()
    r._initialized = True
    return r


# ── load(): 首选 (ai_engines) import 路径全部成功 ───────────────────────────────


class TestLoadPrimaryPath:
    def test_load_uses_ai_engines_primary_imports(self) -> None:
        bert_cls = MagicMock(name="BertCls")
        dist_factory = MagicMock(name="DistilledFactory")
        deep_cls = MagicMock(name="DeepCls")
        rasa_cls = MagicMock(name="RasaCls")
        fakes = {
            "app.ai_engines.bert.intent_service": _make_module(
                "app.ai_engines.bert.intent_service", BertIntentClassifier=bert_cls
            ),
            "app.services.distilled_intent_service": _make_module(
                "app.services.distilled_intent_service",
                get_distilled_recognizer=dist_factory,
            ),
            "app.ai_engines.deepseek.intent_service": _make_module(
                "app.ai_engines.deepseek.intent_service",
                DeepseekIntentClassifier=deep_cls,
            ),
            "app.ai_engines.rasa.nlu_service": _make_module(
                "app.ai_engines.rasa.nlu_service", RasaNLUService=rasa_cls
            ),
        }
        r = UnifiedIntentRecognizer()
        with patch.dict(sys.modules, fakes):
            assert r.load() is True

        assert r._initialized is True
        # 首选工厂/类被实例化并赋值
        assert r.bert_recognizer is bert_cls.return_value
        assert r.distilled_recognizer is dist_factory.return_value
        assert r.deepseek_recognizer is deep_cls.return_value
        assert r.rasa_recognizer is rasa_cls.return_value
        assert r._engine_errors == {}
        # bert/deepseek 有 load_model() 会被调用；rasa 直接调 load_model()
        bert_cls.return_value.load_model.assert_called_once()
        deep_cls.return_value.load_model.assert_called_once()
        rasa_cls.return_value.load_model.assert_called_once()

    def test_load_idempotent_when_already_initialized(self) -> None:
        r = UnifiedIntentRecognizer()
        r._initialized = True
        # 已初始化时直接返回 True，不触碰任何 import
        with patch.dict(sys.modules, {}):
            assert r.load() is True
        assert r.bert_recognizer is None  # 没有真正加载任何引擎


# ── load(): 兼容 (services) fallback import 路径 ────────────────────────────────


class TestLoadFallbackPath:
    def test_load_falls_back_to_services_imports(self) -> None:
        bert2 = MagicMock(name="BertCls2")
        dist_cls = MagicMock(name="DistilledClass")
        deep2 = MagicMock(name="DeepCls2")
        rasa2 = MagicMock(name="RasaCls2")
        fakes = {
            # 首选模块存在但缺少期望符号 -> from-import 抛 ImportError -> 走 fallback
            "app.ai_engines.bert.intent_service": _make_module(
                "app.ai_engines.bert.intent_service"
            ),
            "app.ai_engines.deepseek.intent_service": _make_module(
                "app.ai_engines.deepseek.intent_service"
            ),
            "app.ai_engines.rasa.nlu_service": _make_module("app.ai_engines.rasa.nlu_service"),
            # distilled: 缺 get_distilled_recognizer -> 走 DistilledIntentClassifier 兼容分支
            "app.services.distilled_intent_service": _make_module(
                "app.services.distilled_intent_service",
                DistilledIntentClassifier=dist_cls,
            ),
            # 兼容模块提供类
            "app.services.bert_intent_service": _make_module(
                "app.services.bert_intent_service", BertIntentClassifier=bert2
            ),
            "app.services.deepseek_intent_service": _make_module(
                "app.services.deepseek_intent_service", DeepSeekIntentRecognizer=deep2
            ),
            "app.services.rasa_nlu_service": _make_module(
                "app.services.rasa_nlu_service", RasaNLUService=rasa2
            ),
        }
        r = UnifiedIntentRecognizer()
        with patch.dict(sys.modules, fakes):
            assert r.load() is True

        assert r.bert_recognizer is bert2.return_value
        assert r.distilled_recognizer is dist_cls.return_value
        assert r.deepseek_recognizer is deep2.return_value
        assert r.rasa_recognizer is rasa2.return_value
        assert r._engine_errors == {}
        # distilled 兼容分支会尝试 load_model()
        dist_cls.return_value.load_model.assert_called_once()


# ── load(): 每个子引擎实例化失败 -> _engine_errors 记录 ─────────────────────────


class TestLoadEngineErrors:
    def test_each_engine_failure_recorded(self) -> None:
        def raiser(msg: str):
            def _r(*_a: object, **_k: object):
                raise RuntimeError(msg)

            return _r

        fakes = {
            "app.ai_engines.bert.intent_service": _make_module(
                "app.ai_engines.bert.intent_service",
                BertIntentClassifier=raiser("bert boom"),
            ),
            "app.services.distilled_intent_service": _make_module(
                "app.services.distilled_intent_service",
                get_distilled_recognizer=raiser("dist boom"),
            ),
            "app.ai_engines.deepseek.intent_service": _make_module(
                "app.ai_engines.deepseek.intent_service",
                DeepseekIntentClassifier=raiser("deep boom"),
            ),
            "app.ai_engines.rasa.nlu_service": _make_module(
                "app.ai_engines.rasa.nlu_service",
                RasaNLUService=raiser("rasa boom"),
            ),
        }
        r = UnifiedIntentRecognizer()
        with patch.dict(sys.modules, fakes):
            assert r.load() is True

        # 全部实例化失败 -> 引擎为 None，错误被分别捕获
        assert r.bert_recognizer is None
        assert r.distilled_recognizer is None
        assert r.deepseek_recognizer is None
        assert r.rasa_recognizer is None
        assert set(r._engine_errors) == {"bert", "distilled", "deepseek", "rasa"}
        assert r._engine_errors["bert"] == "bert boom"
        assert r._engine_errors["deepseek"] == "deep boom"
        assert r._engine_errors["rasa"] == "rasa boom"
        # 即使全部失败，load() 仍标记 initialized 并返回 True
        assert r._initialized is True


# ── recognize(): 意图缓存路径 ──────────────────────────────────────────────────


class TestRecognizeCachePath:
    def test_cache_hit_uses_get_or_compute(self, initialized: UnifiedIntentRecognizer) -> None:
        fake_cache = MagicMock()
        fake_cache.get_or_compute.return_value = {
            "intent": "order",
            "confidence": 0.9,
            "source": "distilled",
        }
        with (
            patch(
                "app.domain.ports.cache_port.get_intent_cache_port",
                return_value=fake_cache,
            ),
            patch(
                "app.request_active_mod_ctx.get_request_active_mod_id",
                return_value="mod-1",
            ),
        ):
            out = initialized.recognize("下单")
        assert out == {"intent": "order", "confidence": 0.9, "source": "distilled"}
        kwargs = fake_cache.get_or_compute.call_args.kwargs
        assert kwargs["text"] == "下单"
        assert kwargs["mod_id"] == "mod-1"
        assert callable(kwargs["compute_fn"])

    def test_cache_none_falls_back_to_uncached(self, initialized: UnifiedIntentRecognizer) -> None:
        with patch("app.domain.ports.cache_port.get_intent_cache_port", return_value=None):
            out = initialized.recognize("无引擎文本")
        # 没有任何子引擎 -> unk
        assert out == {"intent": "unk", "confidence": 0.0, "source": "unified"}

    def test_cache_error_falls_back_to_uncached(self, initialized: UnifiedIntentRecognizer) -> None:
        with patch(
            "app.domain.ports.cache_port.get_intent_cache_port",
            side_effect=RuntimeError("cache down"),
        ):
            out = initialized.recognize("无引擎文本")
        assert out["intent"] == "unk"
        assert out["source"] == "unified"

    def test_blank_text_short_circuits_before_cache(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        # 空白文本应在缓存逻辑之前返回 unk（缓存端口绝不被查询）
        with patch("app.domain.ports.cache_port.get_intent_cache_port") as mock_port:
            out = initialized.recognize("   ")
        assert out == {"intent": "unk", "confidence": 0.0, "source": "unified"}
        mock_port.assert_not_called()

    def test_recognize_triggers_load_when_uninitialized(self) -> None:
        r = UnifiedIntentRecognizer()
        calls = {"n": 0}

        def fake_load(self: UnifiedIntentRecognizer) -> bool:
            calls["n"] += 1
            self._initialized = True
            return True

        with patch.object(UnifiedIntentRecognizer, "load", fake_load):
            out = r.recognize("")  # load() 仍被调用，文本空 -> unk
        assert calls["n"] == 1
        assert out["intent"] == "unk"


# ── _recognize_uncached(): 异常与分支 ──────────────────────────────────────────


class TestRecognizeUncachedBranches:
    def test_distilled_exception_falls_to_bert(self, initialized: UnifiedIntentRecognizer) -> None:
        dist = MagicMock()
        dist.predict.side_effect = RuntimeError("distilled boom")
        bert = MagicMock()
        bert.predict.return_value = {"intent": "product", "confidence": 0.85}
        initialized.distilled_recognizer = dist
        initialized.bert_recognizer = bert
        out = initialized._recognize_uncached("查产品")
        assert out["source"] == "bert"
        assert out["intent"] == "product"

    def test_distilled_low_confidence_falls_through(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        dist = MagicMock()
        dist.predict.return_value = {"intent": "x", "confidence": 0.5}
        initialized.distilled_recognizer = dist
        out = initialized._recognize_uncached("x")
        # 低于 0.7 阈值 -> 不选用 distilled，无其他引擎 -> unk
        assert out["intent"] == "unk"

    def test_bert_exception_falls_to_deepseek(self, initialized: UnifiedIntentRecognizer) -> None:
        bert = MagicMock()
        bert.predict.side_effect = RuntimeError("bert boom")
        deep = MagicMock(spec=["predict"])
        deep.predict.return_value = {"intent": "chat", "confidence": 0.95}
        initialized.bert_recognizer = bert
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("聊聊")
        assert out["source"] == "deepseek"

    def test_rasa_disabled_by_env_skips_parse(self, initialized: UnifiedIntentRecognizer) -> None:
        rasa = MagicMock()
        initialized.rasa_recognizer = rasa
        with patch.dict(os.environ, {"ENABLE_RASA": "0"}):
            out = initialized._recognize_uncached("你好")
        rasa.parse.assert_not_called()
        assert out["intent"] == "unk"

    def test_rasa_exception_is_caught(self, initialized: UnifiedIntentRecognizer) -> None:
        rasa = MagicMock()
        rasa.parse.side_effect = RuntimeError("rasa boom")
        initialized.rasa_recognizer = rasa
        with patch.dict(os.environ, {"ENABLE_RASA": "1"}):
            out = initialized._recognize_uncached("你好")
        assert out["intent"] == "unk"

    def test_rasa_low_confidence_not_selected(self, initialized: UnifiedIntentRecognizer) -> None:
        rasa = MagicMock()
        rasa.confidence_threshold = 0.7
        rasa.parse.return_value = {
            "intent": {"name": "greet", "confidence": 0.3},
            "entities": [],
        }
        initialized.rasa_recognizer = rasa
        with patch.dict(os.environ, {"ENABLE_RASA": "1"}):
            out = initialized._recognize_uncached("你好")
        assert out["intent"] == "unk"

    def test_rasa_high_confidence_selected_with_entities(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        rasa = MagicMock()
        rasa.confidence_threshold = 0.6
        rasa.parse.return_value = {
            "intent": {"name": "greet", "confidence": 0.812345},
            "entities": [{"entity": "name", "value": "A"}],
        }
        initialized.rasa_recognizer = rasa
        with patch.dict(os.environ, {"ENABLE_RASA": "1"}):
            out = initialized._recognize_uncached("你好")
        assert out["source"] == "rasa"
        assert out["intent"] == "greet"
        assert out["confidence"] == round(0.812345, 4)
        assert out["entities"] == [{"entity": "name", "value": "A"}]

    def test_deepseek_no_predict_or_recognize_skipped(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        class NoMethod:
            pass

        initialized.deepseek_recognizer = NoMethod()
        out = initialized._recognize_uncached("x")
        assert out["intent"] == "unk"

    def test_deepseek_exception_is_caught(self, initialized: UnifiedIntentRecognizer) -> None:
        deep = MagicMock(spec=["predict"])
        deep.predict.side_effect = RuntimeError("ds boom")
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("x")
        assert out["intent"] == "unk"

    def test_deepseek_non_dict_result_skipped(self, initialized: UnifiedIntentRecognizer) -> None:
        deep = MagicMock(spec=["predict"])
        deep.predict.return_value = "not a dict"
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("x")
        assert out["intent"] == "unk"

    def test_deepseek_low_confidence_skipped(self, initialized: UnifiedIntentRecognizer) -> None:
        deep = MagicMock(spec=["predict"])
        deep.predict.return_value = {"intent": "c", "confidence": 0.2}
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("x")
        assert out["intent"] == "unk"

    def test_deepseek_preserves_explicit_source(self, initialized: UnifiedIntentRecognizer) -> None:
        deep = MagicMock(spec=["predict"])
        deep.predict.return_value = {
            "intent": "c",
            "confidence": 0.9,
            "source": "custom",
        }
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("x")
        # 已有 source 时保留，不覆盖为 "deepseek"
        assert out["source"] == "custom"

    def test_deepseek_via_recognize_method_default_source(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        # 无 predict 但有 recognize -> 使用 recognize；无 source -> 默认 deepseek
        deep = MagicMock(spec=["recognize"])
        deep.recognize.return_value = {"intent": "c", "confidence": 0.9}
        initialized.deepseek_recognizer = deep
        out = initialized._recognize_uncached("x")
        assert out["source"] == "deepseek"
        assert out["intent"] == "c"


# ── is_ready() / get_engine_status() / _rasa_status_snapshot() ──────────────────


class TestReadinessAndStatus:
    def test_is_ready_load_exception_returns_false(self) -> None:
        r = UnifiedIntentRecognizer()
        with patch.object(UnifiedIntentRecognizer, "load", side_effect=RuntimeError("load boom")):
            assert r.is_ready() is False
        assert r._initialized is False

    def test_is_ready_triggers_load_then_true(self) -> None:
        r = UnifiedIntentRecognizer()

        def fake_load(self: UnifiedIntentRecognizer) -> bool:
            self._initialized = True
            return True

        with patch.object(UnifiedIntentRecognizer, "load", fake_load):
            assert r.is_ready() is True

    def test_get_engine_status_triggers_load_when_uninitialized(self) -> None:
        r = UnifiedIntentRecognizer()

        def fake_load(self: UnifiedIntentRecognizer) -> bool:
            self._initialized = True
            return True

        with patch.object(UnifiedIntentRecognizer, "load", fake_load):
            status = r.get_engine_status()
        assert status["rule"]["loaded"] is True
        assert status["distilled"]["loaded"] is False
        assert status["bert"]["loaded"] is False

    def test_get_engine_status_reflects_engine_errors(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        initialized._engine_errors = {"bert": "boom", "deepseek": "down"}
        status = initialized.get_engine_status()
        assert status["bert"]["error"] == "boom"
        assert status["deepseek"]["error"] == "down"
        assert status["distilled"]["error"] is None

    def test_rasa_status_snapshot_merges_get_status(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        rasa = MagicMock()
        rasa.get_status.return_value = {"model": "m1", "ready": True}
        initialized.rasa_recognizer = rasa
        snap = initialized._rasa_status_snapshot()
        assert snap["loaded"] is True
        assert snap["model"] == "m1"
        assert snap["ready"] is True

    def test_rasa_status_snapshot_get_status_exception(
        self, initialized: UnifiedIntentRecognizer
    ) -> None:
        rasa = MagicMock()
        rasa.get_status.side_effect = RuntimeError("status boom")
        initialized.rasa_recognizer = rasa
        snap = initialized._rasa_status_snapshot()
        assert snap["loaded"] is True
        assert snap["status_error"] == "status boom"

    def test_rasa_status_snapshot_no_rasa(self, initialized: UnifiedIntentRecognizer) -> None:
        initialized.rasa_recognizer = None
        snap = initialized._rasa_status_snapshot()
        assert snap == {"loaded": False, "error": None}


# ── 模块级单例 + _env_flag ──────────────────────────────────────────────────────


class TestSingletonAndEnvFlag:
    def test_get_unified_intent_recognizer_singleton(self) -> None:
        with (
            patch.object(uir_mod, "_unified_intent_recognizer", None),
            patch.object(UnifiedIntentRecognizer, "load", lambda self: True),
        ):
            a = uir_mod.get_unified_intent_recognizer()
            b = uir_mod.get_unified_intent_recognizer()
        assert a is b
        assert isinstance(a, UnifiedIntentRecognizer)

    def test_env_flag_default_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UIR_TEST_FLAG", raising=False)
        assert uir_mod._env_flag("UIR_TEST_FLAG") is False

    def test_env_flag_on_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UIR_TEST_FLAG", "on")
        assert uir_mod._env_flag("UIR_TEST_FLAG") is True
