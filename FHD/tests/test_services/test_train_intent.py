"""Behavioral tests for app.services.train_intent.

This is a CLI/orchestration module around an intent-classification stack
(torch + transformers). The module is import-guarded behind ``torch``; CI
without an ML stack skips the whole file via ``importorskip`` below.

The tests below assert *observable behavior* of each entry point:
return values, the exact arguments forwarded to the (mocked) external
trainer/inference stack, the structured log output, and both success/early-exit
branches — not merely "it ran without raising".
"""

# ruff: noqa: E402, I001
from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("torch")
# Guard a real sub-capability of the ML stack, not just package presence.
assert hasattr(__import__("torch"), "cuda")

from app.services.train_intent import (  # noqa: E402
    evaluate_model,
    main,
    serve_model,
    train_model,
)
from app.services.train_intent import (
    test_model as _do_test_model,
)

# ---------------------------------------------------------------------------
# train_model
# ---------------------------------------------------------------------------


def _trainer_stub(return_path: str = "/models/intent_bert/final") -> MagicMock:
    """A stand-in for the ``app.services.intent_trainer`` module."""
    trainer = MagicMock()
    trainer.train_intent_model.return_value = return_path
    return trainer


class TestTrainModel:
    """train_model() — 训练意图识别模型"""

    @patch("app.services.train_intent.torch")
    def test_import_error_returns_none(self, mock_torch):
        """无法导入训练模块时返回 None，且绝不触碰 torch.cuda。"""
        # Forcing the submodule to None makes ``from ... import`` raise ImportError.
        with patch.dict(sys.modules, {"app.services.intent_trainer": None}):
            result = train_model(
                data_path="/tmp/fake.yml",
                model_name="bert-base-chinese",
            )

        assert result is None
        # The function must bail out *before* probing the device.
        mock_torch.cuda.is_available.assert_not_called()

    @patch("app.services.train_intent.torch")
    def test_train_success_returns_stringified_path_and_forwards_defaults(self, mock_torch):
        """训练成功：返回字符串化路径，并按签名默认值转发全部参数。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub("/models/intent_bert/final")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(data_path="/tmp/data.yml")

        assert result == "/models/intent_bert/final"
        assert isinstance(result, str)

        # Exactly one training invocation, carrying the documented default config.
        trainer.train_intent_model.assert_called_once()
        kwargs = trainer.train_intent_model.call_args.kwargs
        assert kwargs == {
            "data_path": "/tmp/data.yml",
            "model_name": "bert-base-chinese",
            "output_dir": "models/intent_bert",
            "num_epochs": 10,
            "batch_size": 16,
            "learning_rate": 2e-5,
            "max_length": 64,
        }
        # No ONNX export unless explicitly requested.
        trainer.export_to_onnx.assert_not_called()

    @patch("app.services.train_intent.torch")
    def test_train_with_custom_params_are_forwarded(self, mock_torch):
        """自定义训练参数逐一映射到 trainer 关键字（epochs→num_epochs 等）。"""
        mock_torch.cuda.is_available.return_value = True
        trainer = _trainer_stub("/models/custom")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(
                data_path="/tmp/data.yml",
                model_name="hfl/chinese-roberta",
                output_dir="models/custom",
                epochs=5,
                batch_size=32,
                learning_rate=3e-5,
                max_length=128,
            )

        assert result == "/models/custom"
        kwargs = trainer.train_intent_model.call_args.kwargs
        assert kwargs == {
            "data_path": "/tmp/data.yml",
            "model_name": "hfl/chinese-roberta",
            "output_dir": "models/custom",
            "num_epochs": 5,
            "batch_size": 32,
            "learning_rate": 3e-5,
            "max_length": 128,
        }

    @patch("app.services.train_intent.torch")
    def test_train_logs_cuda_device_when_available(self, mock_torch, caplog):
        """torch.cuda.is_available()=True 时设备日志为 CUDA。"""
        mock_torch.cuda.is_available.return_value = True
        trainer = _trainer_stub()

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
                train_model(data_path="/tmp/data.yml")

        assert "  设备: CUDA" in caplog.text
        assert "  设备: CPU" not in caplog.text

    @patch("app.services.train_intent.torch")
    def test_train_logs_cpu_device_when_unavailable(self, mock_torch, caplog):
        """torch.cuda.is_available()=False 时设备日志为 CPU。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub()

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
                train_model(data_path="/tmp/data.yml")

        assert "  设备: CPU" in caplog.text

    @patch("app.services.train_intent.torch")
    def test_train_with_export_onnx_uses_output_dir_relative_path(self, mock_torch):
        """export_onnx=True：onnx 路径由 output_dir 派生 (Path(output_dir)/model.onnx)。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub("/models/intent_bert/final")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(data_path="/tmp/data.yml", export_onnx=True)

        # Default output_dir is "models/intent_bert" -> onnx alongside it.
        trainer.export_to_onnx.assert_called_once_with(
            "/models/intent_bert/final",
            "models/intent_bert/model.onnx",
            64,
        )
        # Return value is still the trained model path, not the onnx path.
        assert result == "/models/intent_bert/final"

    @patch("app.services.train_intent.torch")
    def test_train_export_onnx_path_tracks_custom_output_dir(self, mock_torch):
        """export_onnx 的输出路径随 output_dir 与 max_length 变化。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub("/models/custom/final")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            train_model(
                data_path="/tmp/data.yml",
                output_dir="models/custom",
                max_length=128,
                export_onnx=True,
            )

        trainer.export_to_onnx.assert_called_once_with(
            "/models/custom/final",
            "models/custom/model.onnx",
            128,
        )

    @patch("app.services.train_intent.torch")
    def test_train_without_export_onnx_skips_onnx(self, mock_torch):
        """export_onnx=False：训练仍发生，但绝不导出 ONNX。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub("/models/final")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(data_path="/tmp/data.yml", export_onnx=False)

        assert result == "/models/final"
        trainer.train_intent_model.assert_called_once()
        trainer.export_to_onnx.assert_not_called()

    @patch("app.services.train_intent.torch")
    def test_train_recoverable_error_swallowed_returns_none(self, mock_torch):
        """训练抛 RECOVERABLE_ERRORS（如 RuntimeError OOM）→ 捕获并返回 None。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub()
        trainer.train_intent_model.side_effect = RuntimeError("CUDA out of memory")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(data_path="/tmp/data.yml")

        assert result is None
        # ONNX export must not run when training failed.
        trainer.export_to_onnx.assert_not_called()

    @patch("app.services.train_intent.torch")
    def test_train_recoverable_value_error_returns_none(self, mock_torch):
        """ValueError 属于 RECOVERABLE_ERRORS（DATA_SHAPE）→ 同样吞掉返回 None。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub()
        trainer.train_intent_model.side_effect = ValueError("bad nlu.yml")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            result = train_model(data_path="/tmp/data.yml")

        assert result is None

    @patch("app.services.train_intent.torch")
    def test_train_non_recoverable_error_propagates(self, mock_torch):
        """非 RECOVERABLE_ERRORS（如 TypeError）不被吞，向上冒泡。"""
        mock_torch.cuda.is_available.return_value = False
        trainer = _trainer_stub()
        trainer.train_intent_model.side_effect = TypeError("programmer error")

        with patch.dict(sys.modules, {"app.services.intent_trainer": trainer}):
            with pytest.raises(TypeError, match="programmer error"):
                train_model(data_path="/tmp/data.yml")


# ---------------------------------------------------------------------------
# evaluate_model
# ---------------------------------------------------------------------------

# The 15 canonical evaluation samples baked into evaluate_model().
EVAL_TEXTS = [
    "生成发货单",
    "查看客户列表",
    "产品有哪些",
    "发货记录查询",
    "发微信给客户",
    "打印标签",
    "上传Excel",
    "原材料库存",
    "发货单模板",
    "分解Excel",
    "你好",
    "再见",
    "帮帮我",
    "不要生成",
    "导出客户",
]
EVAL_EXPECTED = [
    "shipment_generate",
    "customers",
    "products",
    "shipments",
    "wechat_send",
    "print_label",
    "upload_file",
    "materials",
    "shipment_template",
    "excel_decompose",
    "greet",
    "goodbye",
    "help",
    "negation",
    "customer_export",
]


def _bert_module(classifier: MagicMock) -> MagicMock:
    """A stand-in for the ``app.services.bert_intent_service`` module."""
    svc = MagicMock()
    svc.BertIntentClassifier.return_value = classifier
    return svc


class TestEvaluateModel:
    """evaluate_model() — 评估模型准确率"""

    def test_import_error_returns_early(self):
        """无法导入推理模块时提前返回 None，且从不构造分类器。"""
        marker = MagicMock()  # would be returned if construction happened
        with patch.dict(sys.modules, {"app.services.bert_intent_service": None}):
            result = evaluate_model(model_path="/models/fake")

        assert result is None
        marker.assert_not_called()

    def test_model_not_available_returns_without_predicting(self):
        """模型不可用时提前返回，绝不对样本调用 predict。"""
        classifier = MagicMock()
        classifier.is_available.return_value = False
        svc = _bert_module(classifier)

        with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
            result = evaluate_model(model_path="/models/fake")

        assert result is None
        classifier.predict.assert_not_called()
        # Classifier was constructed with the provided model path.
        svc.BertIntentClassifier.assert_called_once_with(model_path="/models/fake")

    def test_evaluate_predicts_every_canonical_sample_in_order(self):
        """评估对 15 个内置样本逐一预测（顺序、文本均与源码一致）。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {"intent": "x", "confidence": 0.5}
        svc = _bert_module(classifier)

        with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
            evaluate_model(model_path="/models/fake")

        # predict(text) — positional, no return_probs in the eval path.
        called_texts = [c.args[0] for c in classifier.predict.call_args_list]
        assert called_texts == EVAL_TEXTS

    def test_evaluate_all_correct_reports_100_percent(self, caplog):
        """全部命中期望意图 → 准确率 100.00% (15/15)。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        answers = iter(EVAL_EXPECTED)
        classifier.predict.side_effect = lambda text, **kw: {
            "intent": next(answers),
            "confidence": 0.99,
        }
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                evaluate_model(model_path="/models/fake")

        assert "准确率: 100.00% (15/15)" in caplog.text

    def test_evaluate_partial_accuracy_reports_exact_fraction(self, caplog):
        """仅首样本命中 → 准确率 6.67% (1/15)。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        predictions = iter(
            [{"intent": "shipment_generate", "confidence": 0.9}]
            + [{"intent": "WRONG", "confidence": 0.3}] * 14
        )
        classifier.predict.side_effect = lambda text, **kw: next(predictions)
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                evaluate_model(model_path="/models/fake")

        # 1/15 * 100 == 6.666... -> formatted "6.67%".
        assert "准确率: 6.67% (1/15)" in caplog.text
        # The first sample is correct (✓), the rest wrong (✗).
        assert "✓ '生成发货单'" in caplog.text
        assert "✗ '查看客户列表'" in caplog.text

    def test_evaluate_all_wrong_reports_zero(self, caplog):
        """全部预测错误 → 准确率 0.00% (0/15)。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {"intent": "__never__", "confidence": 0.1}
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                evaluate_model(model_path="/models/fake")

        assert "准确率: 0.00% (0/15)" in caplog.text


# ---------------------------------------------------------------------------
# test_model (renamed to avoid pytest collection)
# ---------------------------------------------------------------------------


class TestBatchTestModel:
    """_do_test_model() — 批量测试模型"""

    def test_import_error_returns_early(self):
        """无法导入推理模块时提前返回 None。"""
        with patch.dict(sys.modules, {"app.services.bert_intent_service": None}):
            result = _do_test_model(model_path="/models/fake", texts=["你好"])
        assert result is None

    def test_predicts_each_text_with_return_probs(self):
        """对每个文本以 return_probs=True 调用 predict。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.99,
            "all_probs": {"greet": 0.99, "help": 0.01},
        }
        svc = _bert_module(classifier)

        with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
            _do_test_model(model_path="/models/fake", texts=["你好", "再见"])

        called_texts = [c.args[0] for c in classifier.predict.call_args_list]
        assert called_texts == ["你好", "再见"]
        # Probabilities must be requested for the Top-3 readout.
        for call in classifier.predict.call_args_list:
            assert call.kwargs.get("return_probs") is True

    def test_logs_intent_and_top3_when_probs_present(self, caplog):
        """有 all_probs 时输出意图、置信度与按概率降序的 Top-3。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.8123,
            "all_probs": {
                "greet": 0.81,
                "help": 0.12,
                "goodbye": 0.05,
                "negation": 0.02,
            },
        }
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                _do_test_model(model_path="/models/fake", texts=["你好"])

        text = caplog.text
        assert "文本: 你好" in text
        assert "意图: greet" in text
        assert "置信度: 0.8123" in text
        # Top-3 only, sorted desc by probability; the 4th (negation) excluded.
        assert "greet: 0.8100" in text
        assert "help: 0.1200" in text
        assert "goodbye: 0.0500" in text
        assert "negation" not in text
        # Ordering: greet before help before goodbye in the Top-3 line.
        top3_idx = text.index("Top-3")
        assert (
            text.index("greet:", top3_idx)
            < text.index("help:", top3_idx)
            < text.index("goodbye:", top3_idx)
        )

    def test_no_all_probs_key_skips_top3(self, caplog):
        """predict 结果缺少 all_probs 键时不输出 Top-3，但仍记录意图。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {"intent": "greet", "confidence": 0.8}
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                _do_test_model(model_path="/models/fake", texts=["你好"])

        assert "意图: greet" in caplog.text
        assert "Top-3" not in caplog.text

    def test_empty_all_probs_skips_top3(self, caplog):
        """all_probs 为空字典（falsy）时不输出 Top-3。"""
        classifier = MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.5,
            "all_probs": {},
        }
        svc = _bert_module(classifier)

        with caplog.at_level(logging.INFO, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                _do_test_model(model_path="/models/fake", texts=["你好"])

        assert "意图: greet" in caplog.text
        assert "Top-3" not in caplog.text

    def test_unavailable_warns_but_still_predicts(self, caplog):
        """模型不可用时发出警告，但仍对文本继续预测（虚拟预测路径）。"""
        classifier = MagicMock()
        classifier.is_available.return_value = False
        classifier.predict.return_value = {"intent": "unknown", "confidence": 0.0}
        svc = _bert_module(classifier)

        with caplog.at_level(logging.WARNING, logger="app.services.train_intent"):
            with patch.dict(sys.modules, {"app.services.bert_intent_service": svc}):
                _do_test_model(model_path="/models/fake", texts=["你好"])

        assert "模型不可用" in caplog.text
        classifier.predict.assert_called_once()


# ---------------------------------------------------------------------------
# serve_model
# ---------------------------------------------------------------------------


class TestServeModel:
    """serve_model() — 启动 FastAPI 意图推理服务"""

    def test_serve_builds_app_and_runs_uvicorn_on_given_port(self):
        """serve_model 构造分类器、注册 predict 路由并以指定端口启动 uvicorn。"""
        classifier = MagicMock()
        svc = _bert_module(classifier)
        mock_uvicorn = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "app.services.bert_intent_service": svc,
                "uvicorn": mock_uvicorn,
            },
        ):
            serve_model(model_path="/models/fake", port=8080)

        # Classifier constructed from the requested model path.
        svc.BertIntentClassifier.assert_called_once_with(model_path="/models/fake")

        mock_uvicorn.run.assert_called_once()
        run_args, run_kwargs = mock_uvicorn.run.call_args
        # A FastAPI app instance is passed positionally; host/port forwarded.
        app = run_args[0]
        assert app.title == "xcagi-intent-serve"
        assert run_kwargs["host"] == "0.0.0.0"
        assert run_kwargs["port"] == 8080

        # The predict route is wired onto the app.
        routes = {getattr(r, "path", None) for r in app.routes}
        assert "/api/intent/predict" in routes

    def test_serve_predict_route_delegates_to_classifier(self):
        """注册的 /api/intent/predict 路由把文本下发给 classifier.predict。"""
        from fastapi.testclient import TestClient

        classifier = MagicMock()
        classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.9,
            "all_probs": {"greet": 0.9},
        }
        svc = _bert_module(classifier)
        mock_uvicorn = MagicMock()

        captured: dict[str, object] = {}

        def _capture_app(app, **kw):
            captured["app"] = app

        mock_uvicorn.run.side_effect = _capture_app

        with patch.dict(
            sys.modules,
            {
                "app.services.bert_intent_service": svc,
                "uvicorn": mock_uvicorn,
            },
        ):
            serve_model(model_path="/models/fake", port=5001)

        app = captured["app"]
        client = TestClient(app)
        resp = client.post("/api/intent/predict", json={"text": "你好"})

        assert resp.status_code == 200
        assert resp.json() == {
            "intent": "greet",
            "confidence": 0.9,
            "all_probs": {"greet": 0.9},
        }
        classifier.predict.assert_called_once_with("你好", return_probs=True)

    def test_serve_predict_route_coerces_missing_text_to_empty(self):
        """请求体缺少 text 时，路由以空串调用 predict（不报错）。"""
        from fastapi.testclient import TestClient

        classifier = MagicMock()
        classifier.predict.return_value = {"intent": "unknown", "confidence": 0.0}
        svc = _bert_module(classifier)
        mock_uvicorn = MagicMock()
        captured: dict[str, object] = {}
        mock_uvicorn.run.side_effect = lambda app, **kw: captured.update(app=app)

        with patch.dict(
            sys.modules,
            {
                "app.services.bert_intent_service": svc,
                "uvicorn": mock_uvicorn,
            },
        ):
            serve_model(model_path="/models/fake", port=5002)

        client = TestClient(captured["app"])
        resp = client.post("/api/intent/predict", json={})

        assert resp.status_code == 200
        classifier.predict.assert_called_once_with("", return_probs=True)


# ---------------------------------------------------------------------------
# main() — CLI argument parsing
# ---------------------------------------------------------------------------


class TestMain:
    """main() — CLI 入口"""

    @patch("app.services.train_intent.train_model")
    def test_train_mode_without_data_returns_early(self, mock_train, caplog):
        """train 模式缺 --data 时记录错误并提前返回，绝不调用 train_model。"""
        with caplog.at_level(logging.ERROR, logger="app.services.train_intent"):
            with patch("sys.argv", ["train_intent", "--mode", "train"]):
                main()

        mock_train.assert_not_called()
        assert "需要指定 --data" in caplog.text

    @patch("app.services.train_intent.train_model")
    def test_train_mode_with_data_uses_defaults(self, mock_train):
        """train 模式给了 --data：以 CLI 默认值调用 train_model。"""
        mock_train.return_value = "/models/final"
        with patch(
            "sys.argv",
            ["train_intent", "--mode", "train", "--data", "/tmp/data.yml"],
        ):
            main()

        mock_train.assert_called_once_with(
            data_path="/tmp/data.yml",
            model_name="models/intent_bert/final",
            output_dir="models/intent_bert",
            epochs=10,
            batch_size=16,
            learning_rate=2e-5,
            max_length=64,
            export_onnx=False,
        )

    @patch("app.services.train_intent.evaluate_model")
    def test_evaluate_mode_forwards_model_and_data(self, mock_eval):
        """evaluate 模式把 --model/--data 转发给 evaluate_model。"""
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "evaluate",
                "--model",
                "/models/final",
                "--data",
                "/tmp/eval.yml",
            ],
        ):
            main()
        mock_eval.assert_called_once_with(model_path="/models/final", data_path="/tmp/eval.yml")

    @patch("app.services.train_intent.test_model")
    def test_test_mode_splits_texts_on_pipe(self, mock_test):
        """test 模式按 | 切分 --texts 为列表。"""
        with patch(
            "sys.argv",
            ["train_intent", "--mode", "test", "--texts", "你好|再见|帮帮我"],
        ):
            main()

        mock_test.assert_called_once_with(
            model_path="models/intent_bert/final",
            texts=["你好", "再见", "帮帮我"],
        )

    @patch("app.services.train_intent.test_model")
    def test_test_mode_without_texts_uses_defaults(self, mock_test):
        """test 模式无 --texts 时使用内置默认文本对。"""
        with patch("sys.argv", ["train_intent", "--mode", "test"]):
            main()

        mock_test.assert_called_once_with(
            model_path="models/intent_bert/final",
            texts=["生成发货单", "查看客户"],
        )

    @patch("app.services.train_intent.serve_model")
    def test_serve_mode_forwards_default_model_and_port(self, mock_serve):
        """serve 模式把默认模型与指定端口转发给 serve_model。"""
        with patch(
            "sys.argv",
            ["train_intent", "--mode", "serve", "--port", "9000"],
        ):
            main()
        mock_serve.assert_called_once_with(model_path="models/intent_bert/final", port=9000)

    @patch("app.services.train_intent.train_model")
    def test_train_mode_with_all_args(self, mock_train):
        """train 模式逐参解析并完整转发（含 --export_onnx 旗标）。"""
        mock_train.return_value = "/models/final"
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "train",
                "--data",
                "/tmp/data.yml",
                "--model",
                "bert-base",
                "--output",
                "models/out",
                "--epochs",
                "5",
                "--batch_size",
                "32",
                "--lr",
                "3e-5",
                "--max_length",
                "128",
                "--export_onnx",
            ],
        ):
            main()
        mock_train.assert_called_once_with(
            data_path="/tmp/data.yml",
            model_name="bert-base",
            output_dir="models/out",
            epochs=5,
            batch_size=32,
            learning_rate=3e-5,
            max_length=128,
            export_onnx=True,
        )

    def test_invalid_mode_exits_with_error(self):
        """非法 --mode 触发 argparse SystemExit（退出码 2）。"""
        with patch("sys.argv", ["train_intent", "--mode", "nonsense"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
