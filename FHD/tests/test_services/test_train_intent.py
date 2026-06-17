"""Tests for app.services.train_intent — intent model training/evaluation/serve CLI."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# torch is an optional dependency; provide a stub so the module can be imported.
if "torch" not in sys.modules:
    _torch_stub = MagicMock()
    _torch_stub.cuda.is_available.return_value = False
    sys.modules["torch"] = _torch_stub

from app.services.train_intent import (
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


class TestTrainModel:
    """train_model() — 训练意图识别模型"""

    @patch("app.services.train_intent.torch")
    def test_import_error_returns_none(self, mock_torch):
        """无法导入训练模块时返回 None"""
        with patch.dict(sys.modules, {"app.services.intent_trainer": None}):
            with patch(
                "app.services.train_intent.train_intent_model",
                side_effect=ImportError("no module"),
                create=True,
            ):
                result = train_model(
                    data_path="/tmp/fake.yml",
                    model_name="bert-base-chinese",
                )
        assert result is None

    @patch("app.services.train_intent.torch")
    def test_train_success_returns_path(self, mock_torch):
        """训练成功返回模型路径"""
        mock_torch.cuda.is_available.return_value = False

        mock_trainer = MagicMock()
        mock_trainer.train_intent_model.return_value = "/models/intent_bert/final"

        with patch.dict(
            sys.modules,
            {"app.services.intent_trainer": mock_trainer},
        ):
            result = train_model(data_path="/tmp/data.yml")

        assert result == "/models/intent_bert/final"
        mock_trainer.train_intent_model.assert_called_once()

    @patch("app.services.train_intent.torch")
    def test_train_with_custom_params(self, mock_torch):
        """自定义训练参数正确传递"""
        mock_torch.cuda.is_available.return_value = True

        mock_trainer = MagicMock()
        mock_trainer.train_intent_model.return_value = "/models/custom"

        with patch.dict(
            sys.modules,
            {"app.services.intent_trainer": mock_trainer},
        ):
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
        call_kwargs = mock_trainer.train_intent_model.call_args
        assert call_kwargs.kwargs.get("num_epochs") == 5
        assert call_kwargs.kwargs.get("batch_size") == 32
        assert call_kwargs.kwargs.get("learning_rate") == 3e-5
        assert call_kwargs.kwargs.get("max_length") == 128

    @patch("app.services.train_intent.torch")
    def test_train_with_export_onnx(self, mock_torch):
        """export_onnx=True 时调用 export_to_onnx"""
        mock_torch.cuda.is_available.return_value = False

        mock_trainer = MagicMock()
        mock_trainer.train_intent_model.return_value = "/models/intent_bert/final"

        with patch.dict(
            sys.modules,
            {"app.services.intent_trainer": mock_trainer},
        ):
            result = train_model(
                data_path="/tmp/data.yml",
                export_onnx=True,
            )

        mock_trainer.export_to_onnx.assert_called_once_with(
            "/models/intent_bert/final",
            "models/intent_bert/model.onnx",
            64,
        )

    @patch("app.services.train_intent.torch")
    def test_train_without_export_onnx(self, mock_torch):
        """export_onnx=False 时不调用 export_to_onnx"""
        mock_torch.cuda.is_available.return_value = False

        mock_trainer = MagicMock()
        mock_trainer.train_intent_model.return_value = "/models/final"

        with patch.dict(
            sys.modules,
            {"app.services.intent_trainer": mock_trainer},
        ):
            train_model(data_path="/tmp/data.yml", export_onnx=False)

        mock_trainer.export_to_onnx.assert_not_called()

    @patch("app.services.train_intent.torch")
    def test_train_recoverable_error_returns_none(self, mock_torch):
        """训练过程抛出 RECOVERABLE_ERRORS 时返回 None"""
        mock_torch.cuda.is_available.return_value = False

        mock_trainer = MagicMock()
        mock_trainer.train_intent_model.side_effect = RuntimeError("OOM")

        with patch.dict(
            sys.modules,
            {"app.services.intent_trainer": mock_trainer},
        ):
            result = train_model(data_path="/tmp/data.yml")

        assert result is None


# ---------------------------------------------------------------------------
# evaluate_model
# ---------------------------------------------------------------------------


class TestEvaluateModel:
    """evaluate_model() — 评估模型准确率"""

    def test_import_error_returns_early(self):
        """无法导入推理模块时提前返回"""
        with patch.dict(sys.modules, {"app.services.bert_intent_service": None}):
            result = evaluate_model(model_path="/models/fake")
        assert result is None

    def test_model_not_available_returns_early(self):
        """模型不可用时提前返回"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = False
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            result = evaluate_model(model_path="/models/fake")

        assert result is None

    def test_evaluate_runs_all_samples(self):
        """评估运行所有测试样本并计算准确率"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True
        mock_classifier.predict.return_value = {"intent": "shipment_generate", "confidence": 0.95}
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            evaluate_model(model_path="/models/fake")

        assert mock_classifier.predict.call_count == 15

    def test_evaluate_partial_accuracy(self):
        """部分正确预测时准确率介于 0-100%"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True

        predictions = iter(
            [{"intent": "shipment_generate", "confidence": 0.9}]
            + [{"intent": "wrong", "confidence": 0.3}] * 14
        )
        mock_classifier.predict.side_effect = lambda text, **kw: next(predictions)
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            evaluate_model(model_path="/models/fake")


# ---------------------------------------------------------------------------
# test_model (renamed to avoid pytest collection)
# ---------------------------------------------------------------------------


class TestBatchTestModel:
    """_do_test_model() — 批量测试模型"""

    def test_import_error_returns_early(self):
        """无法导入推理模块时提前返回"""
        with patch.dict(sys.modules, {"app.services.bert_intent_service": None}):
            result = _do_test_model(model_path="/models/fake", texts=["你好"])
        assert result is None

    def test_with_texts(self):
        """传入文本列表时对每个文本调用 predict"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True
        mock_classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.99,
            "all_probs": {"greet": 0.99, "help": 0.01},
        }
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            _do_test_model(model_path="/models/fake", texts=["你好", "再见"])

        assert mock_classifier.predict.call_count == 2

    def test_no_all_probs(self):
        """predict 结果无 all_probs 时不报错"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True
        mock_classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.8,
        }
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            _do_test_model(model_path="/models/fake", texts=["你好"])

    def test_empty_all_probs(self):
        """all_probs 为空字典时不报错"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True
        mock_classifier.predict.return_value = {
            "intent": "greet",
            "confidence": 0.5,
            "all_probs": {},
        }
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            _do_test_model(model_path="/models/fake", texts=["你好"])

    def test_unavailable_warns(self):
        """模型不可用时输出警告但仍运行"""
        mock_svc = MagicMock()
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = False
        mock_classifier.predict.return_value = {"intent": "unknown", "confidence": 0.0}
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        with patch.dict(
            sys.modules,
            {"app.services.bert_intent_service": mock_svc},
        ):
            _do_test_model(model_path="/models/fake", texts=["你好"])


# ---------------------------------------------------------------------------
# serve_model
# ---------------------------------------------------------------------------


class TestServeModel:
    """serve_model() — 启动 FastAPI 意图推理服务"""

    def test_serve_creates_app_and_runs_uvicorn(self):
        """serve_model 创建 FastAPI app 并调用 uvicorn.run"""
        mock_classifier = MagicMock()
        mock_svc = MagicMock()
        mock_svc.BertIntentClassifier.return_value = mock_classifier

        mock_uvicorn = MagicMock()

        with (
            patch.dict(
                sys.modules,
                {
                    "app.services.bert_intent_service": mock_svc,
                    "uvicorn": mock_uvicorn,
                },
            ),
        ):
            serve_model(model_path="/models/fake", port=8080)

        mock_uvicorn.run.assert_called_once()


# ---------------------------------------------------------------------------
# main() — CLI argument parsing
# ---------------------------------------------------------------------------


class TestMain:
    """main() — CLI 入口"""

    def test_train_mode_without_data_returns_early(self, capsys):
        """train 模式无 --data 时提前返回"""
        with patch("sys.argv", ["train_intent", "--mode", "train"]):
            main()

    @patch("app.services.train_intent.train_model")
    def test_train_mode_with_data(self, mock_train):
        """train 模式有 --data 时调用 train_model"""
        mock_train.return_value = "/models/final"
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "train",
                "--data",
                "/tmp/data.yml",
            ],
        ):
            main()
        mock_train.assert_called_once()

    @patch("app.services.train_intent.evaluate_model")
    def test_evaluate_mode(self, mock_eval):
        """evaluate 模式调用 evaluate_model"""
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "evaluate",
                "--model",
                "/models/final",
            ],
        ):
            main()
        mock_eval.assert_called_once_with(model_path="/models/final", data_path=None)

    @patch(
        "app.services.train_intent._do_test_model"
        if False
        else "app.services.train_intent.test_model"
    )
    def test_test_mode_with_texts(self, mock_test):
        """test 模式解析 --texts 参数"""
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "test",
                "--texts",
                "你好|再见",
            ],
        ):
            main()
        mock_test.assert_called_once()
        call_kwargs = mock_test.call_args
        texts = call_kwargs.kwargs.get("texts") or call_kwargs[1].get("texts")
        assert texts == ["你好", "再见"]

    @patch("app.services.train_intent.test_model")
    def test_test_mode_without_texts_uses_defaults(self, mock_test):
        """test 模式无 --texts 时使用默认文本"""
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "test",
            ],
        ):
            main()
        mock_test.assert_called_once()
        call_kwargs = mock_test.call_args
        texts = call_kwargs.kwargs.get("texts") or call_kwargs[1].get("texts")
        assert "生成发货单" in texts

    @patch("app.services.train_intent.serve_model")
    def test_serve_mode(self, mock_serve):
        """serve 模式调用 serve_model"""
        with patch(
            "sys.argv",
            [
                "train_intent",
                "--mode",
                "serve",
                "--port",
                "9000",
            ],
        ):
            main()
        mock_serve.assert_called_once_with(model_path="models/intent_bert/final", port=9000)

    @patch("app.services.train_intent.train_model")
    def test_train_mode_with_all_args(self, mock_train):
        """train 模式传递所有参数"""
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
