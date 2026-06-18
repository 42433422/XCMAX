"""测试蒸馏训练器模块。

注意：distillation_trainer 依赖 torch / transformers 等重量级库，
在 CI 环境中可能不可用。因此测试通过 mock 或条件导入来覆盖核心逻辑。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# 尝试导入，如果 torch 不可用则跳过需要真实 torch 的测试
torch_available = True
try:
    import torch
except ImportError:
    torch_available = False

# 条件导入被测模块
try:
    from app.services.distillation_trainer import (
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        DistillationDataset,
        DistillationTrainer,
    )
except ImportError:
    pytest.skip("distillation_trainer 依赖不可用", allow_module_level=True)


class TestIntentLabels:
    """测试意图标签常量。"""

    def test_intent_labels_not_empty(self):
        assert len(INTENT_LABELS) > 0

    def test_label_to_id_bijective(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_label_to_id_contains_known_intents(self):
        for intent in ("shipment_generate", "customers", "greet", "unk"):
            assert intent in LABEL_TO_ID

    def test_id_to_label_keys_are_contiguous(self):
        keys = sorted(ID_TO_LABEL.keys())
        assert keys == list(range(len(INTENT_LABELS)))


class TestDistillationDataset:
    """测试蒸馏数据集类。"""

    def test_len_returns_text_count(self):
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(squeeze=lambda dim: MagicMock()),
            "attention_mask": MagicMock(squeeze=lambda dim: MagicMock()),
        }
        texts = ["你好", "帮我开单"]
        labels = [0, 1]
        ds = DistillationDataset(texts, labels, mock_tokenizer)
        assert len(ds) == 2

    def test_len_empty(self):
        mock_tokenizer = MagicMock()
        ds = DistillationDataset([], [], mock_tokenizer)
        assert len(ds) == 0

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_returns_dict_with_expected_keys(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        texts = ["你好"]
        labels = [0]
        ds = DistillationDataset(texts, labels, mock_tokenizer, max_length=8)
        item = ds[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_label_is_long_tensor(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }
        ds = DistillationDataset(["test"], [5], mock_tokenizer)
        item = ds[0]
        assert item["labels"].dtype == torch.long
        assert item["labels"].item() == 5

    def test_getitem_calls_tokenizer_with_correct_args(self):
        mock_tokenizer = MagicMock()
        mock_input_ids = MagicMock()
        mock_attention_mask = MagicMock()
        mock_input_ids.squeeze.return_value = mock_input_ids
        mock_attention_mask.squeeze.return_value = mock_attention_mask
        mock_tokenizer.return_value = {
            "input_ids": mock_input_ids,
            "attention_mask": mock_attention_mask,
        }
        ds = DistillationDataset(["hello"], [0], mock_tokenizer, max_length=32)
        _ = ds[0]
        mock_tokenizer.assert_called_once_with(
            "hello", max_length=32, padding="max_length", truncation=True, return_tensors="pt"
        )


class TestDistillationTrainerInit:
    """测试 DistillationTrainer 初始化。"""

    def test_explicit_device_cpu(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.device == "cpu"

    def test_default_hyperparameters(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.num_labels == len(INTENT_LABELS)
        assert trainer.max_length == 64
        assert trainer.learning_rate == 2e-5
        assert trainer.batch_size == 16
        assert trainer.epochs == 3
        assert trainer.warmup_ratio == 0.1

    def test_custom_hyperparameters(self):
        trainer = DistillationTrainer(
            device="cpu",
            max_length=128,
            learning_rate=1e-4,
            batch_size=32,
            epochs=5,
            warmup_ratio=0.2,
        )
        assert trainer.max_length == 128
        assert trainer.learning_rate == 1e-4
        assert trainer.batch_size == 32
        assert trainer.epochs == 5
        assert trainer.warmup_ratio == 0.2

    def test_model_name_default(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.model_name == "hfl/chinese-bert-wwm-ext"

    def test_initial_state_none(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.tokenizer is None
        assert trainer.model is None
        assert trainer.train_loader is None
        assert trainer.val_loader is None


class TestDistillationTrainerLoadData:
    """测试数据加载功能。"""

    def test_load_jsonl_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "你好", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps({"text": "开单", "label": "shipment_generate"}, ensure_ascii=False)
                + "\n"
            )

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2
        assert "你好" in texts
        assert labels[0] == LABEL_TO_ID["greet"]
        assert labels[1] == LABEL_TO_ID["shipment_generate"]

    def test_load_jsonl_skips_unknown_labels(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "你好", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps({"text": "unknown", "label": "nonexistent_label"}, ensure_ascii=False)
                + "\n"
            )

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_jsonl_default_label_is_unk(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "something"}, ensure_ascii=False) + "\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1
        assert labels[0] == LABEL_TO_ID["unk"]

    def test_load_tsv_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("你好\tgreet\n")
            f.write("开单\tshipment_generate\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2

    def test_load_tsv_skips_short_lines(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("only_one_column\n")
            f.write("你好\tgreet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_tsv_skips_unknown_labels(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("hello\tunknown_label\n")
            f.write("你好\tgreet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_empty_file(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "empty.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            pass

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0
        assert len(labels) == 0

    def test_load_unsupported_format(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.csv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text,label\nhello,greet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0


class TestDistillationTrainerSaveCheckpoint:
    """测试检查点保存。"""

    def test_save_checkpoint_creates_config(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        os.makedirs(checkpoint_path, exist_ok=True)

        with patch(
            "app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "checkpoints")
        ):
            os.makedirs(str(tmp_path / "checkpoints"), exist_ok=True)
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=True)

        config_path = os.path.join(checkpoint_path, "train_config.json")
        assert os.path.exists(config_path)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["epoch"] == 1
        assert config["best"] is True
        assert config["num_labels"] == len(INTENT_LABELS)
        assert "saved_at" in config

    def test_save_checkpoint_saves_model_and_tokenizer(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        os.makedirs(checkpoint_path, exist_ok=True)

        with patch(
            "app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "checkpoints")
        ):
            os.makedirs(str(tmp_path / "checkpoints"), exist_ok=True)
            trainer.save_checkpoint(checkpoint_path, epoch=2, best=False)

        trainer.model.save_pretrained.assert_called_once_with(checkpoint_path)
        trainer.tokenizer.save_pretrained.assert_called_once_with(checkpoint_path)

    def test_save_checkpoint_creates_vocab(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=False)

        vocab_path = os.path.join(ckpt_dir, "vocab.json")
        assert os.path.exists(vocab_path)
        with open(vocab_path, encoding="utf-8") as f:
            vocab = json.load(f)
        assert "id2label" in vocab
        assert "label2id" in vocab


class TestDistillationTrainerTrain:
    """测试完整训练流程的边界条件。"""

    def test_train_returns_early_with_insufficient_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", epochs=1)
        data_path = str(tmp_path / "small.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(
                    json.dumps({"text": f"text{i}", "label": "greet"}, ensure_ascii=False) + "\n"
                )

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "ckpt")):
            with patch("app.services.distillation_trainer.LOG_DIR", str(tmp_path / "logs")):
                result = trainer.train(data_path, output_dir=str(tmp_path / "ckpt"))
        assert result is None


class TestDistillationTrainerPrepareData:
    """测试 prepare_data 方法（mock 模型加载）。"""

    def test_prepare_data_sets_tokenizer_and_model(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", batch_size=2)
        texts = ["你好", "开单", "查客户", "打印"]
        labels = [
            LABEL_TO_ID["greet"],
            LABEL_TO_ID["shipment_generate"],
            LABEL_TO_ID["customers"],
            LABEL_TO_ID["print_label"],
        ]

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        with (
            patch("app.services.distillation_trainer.BertTokenizer") as MockTokenizer,
            patch("app.services.distillation_trainer.BertForSequenceClassification") as MockModel,
            patch("app.services.distillation_trainer.DataLoader") as MockDataLoader,
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockModel.from_pretrained.return_value = mock_model
            MockDataLoader.return_value = MagicMock()

            trainer.prepare_data(texts, labels, val_ratio=0.5)

        assert trainer.tokenizer is mock_tokenizer
        assert trainer.model is mock_model
        mock_model.to.assert_called_once_with("cpu")

    def test_prepare_data_creates_data_loaders(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", batch_size=2)
        texts = ["你好", "开单", "查客户", "打印"]
        labels = [0, 1, 2, 3]

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        with (
            patch("app.services.distillation_trainer.BertTokenizer") as MockTokenizer,
            patch("app.services.distillation_trainer.BertForSequenceClassification") as MockModel,
            patch("app.services.distillation_trainer.DataLoader") as MockDataLoader,
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockModel.from_pretrained.return_value = mock_model
            MockDataLoader.return_value = MagicMock()

            trainer.prepare_data(texts, labels, val_ratio=0.5)

        assert trainer.train_loader is not None
        assert trainer.val_loader is not None

    def test_prepare_data_small_dataset_no_stratify(self):
        """Few labels / few samples should not use stratified split."""
        trainer = DistillationTrainer(device="cpu", batch_size=2)
        texts = ["a", "b"]
        labels = [0, 0]

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        with (
            patch("app.services.distillation_trainer.BertTokenizer") as MockTokenizer,
            patch("app.services.distillation_trainer.BertForSequenceClassification") as MockModel,
            patch("app.services.distillation_trainer.DataLoader") as MockDataLoader,
            patch("app.services.distillation_trainer.train_test_split") as mock_split,
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockModel.from_pretrained.return_value = mock_model
            MockDataLoader.return_value = MagicMock()
            mock_split.return_value = (texts, texts, labels, labels)

            trainer.prepare_data(texts, labels, val_ratio=0.5)

            # Should not use stratify for small data
            call_kwargs = mock_split.call_args[1]
            assert "stratify" not in call_kwargs or call_kwargs["stratify"] is None


class TestDistillationTrainerTrainEpoch:
    """测试 train_epoch 方法（mock 模型前向传播）。"""

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_train_epoch_returns_loss_and_accuracy(self):
        import torch

        trainer = DistillationTrainer(device="cpu", batch_size=2)

        # Mock model
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.loss = torch.tensor(0.5)
        mock_output.logits = torch.tensor([[0.8, 0.2]])
        mock_model.return_value = mock_output
        mock_model.parameters.return_value = []
        trainer.model = mock_model

        # Mock train_loader
        mock_batch = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
            "labels": torch.tensor([0]),
        }
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([mock_batch]))
        mock_loader.__len__ = MagicMock(return_value=1)
        trainer.train_loader = mock_loader

        mock_optimizer = MagicMock()
        mock_scheduler = MagicMock()

        with patch("torch.nn.utils.clip_grad_norm_"):
            avg_loss, accuracy = trainer.train_epoch(mock_optimizer, mock_scheduler)

        assert isinstance(avg_loss, float)
        assert isinstance(accuracy, float)
        assert avg_loss >= 0
        assert 0 <= accuracy <= 1

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_train_epoch_calls_optimizer_step(self):
        import torch

        trainer = DistillationTrainer(device="cpu")
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.loss = torch.tensor(0.3, requires_grad=True)
        mock_output.logits = torch.tensor([[0.6, 0.4]])
        mock_model.return_value = mock_output
        mock_model.parameters.return_value = [torch.randn(2, 2, requires_grad=True)]
        trainer.model = mock_model

        mock_batch = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.tensor([[1]]),
            "labels": torch.tensor([0]),
        }
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([mock_batch]))
        mock_loader.__len__ = MagicMock(return_value=1)
        trainer.train_loader = mock_loader

        mock_optimizer = MagicMock()
        mock_scheduler = MagicMock()

        with patch("torch.nn.utils.clip_grad_norm_"):
            trainer.train_epoch(mock_optimizer, mock_scheduler)

        mock_optimizer.zero_grad.assert_called()
        mock_optimizer.step.assert_called()
        mock_scheduler.step.assert_called()


class TestDistillationTrainerEvaluate:
    """测试 evaluate 方法。"""

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_evaluate_returns_metrics(self):
        import torch

        trainer = DistillationTrainer(device="cpu")
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.loss = torch.tensor(0.4)
        mock_output.logits = torch.tensor([[0.9, 0.1]])
        mock_model.return_value = mock_output
        trainer.model = mock_model

        mock_batch = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
            "labels": torch.tensor([0]),
        }
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([mock_batch]))
        mock_loader.__len__ = MagicMock(return_value=1)
        trainer.val_loader = mock_loader

        result = trainer.evaluate()
        assert "val_loss" in result
        assert "val_accuracy" in result
        assert "preds" in result
        assert "labels" in result
        assert isinstance(result["val_loss"], float)
        assert 0 <= result["val_accuracy"] <= 1

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_evaluate_perfect_accuracy(self):
        import torch

        trainer = DistillationTrainer(device="cpu")
        mock_model = MagicMock()
        # Logits that predict class 0 with high confidence
        mock_output = MagicMock()
        mock_output.loss = torch.tensor(0.01)
        mock_output.logits = torch.tensor([[10.0, 0.0]])
        mock_model.return_value = mock_output
        trainer.model = mock_model

        mock_batch = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.tensor([[1]]),
            "labels": torch.tensor([0]),
        }
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([mock_batch]))
        mock_loader.__len__ = MagicMock(return_value=1)
        trainer.val_loader = mock_loader

        result = trainer.evaluate()
        assert result["val_accuracy"] == 1.0


class TestDistillationTrainerTrainFull:
    """测试完整 train 方法（mock 所有依赖）。"""

    def test_train_full_flow_with_mock(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", epochs=1, batch_size=2)

        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for label_name in INTENT_LABELS[:5]:
                for i in range(5):
                    f.write(
                        json.dumps(
                            {"text": f"text_{label_name}_{i}", "label": label_name},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_model.parameters.return_value = []

        with (
            patch("app.services.distillation_trainer.BertTokenizer") as MockTokenizer,
            patch("app.services.distillation_trainer.BertForSequenceClassification") as MockModel,
            patch("app.services.distillation_trainer.AdamW") as MockAdamW,
            patch(
                "app.services.distillation_trainer.get_linear_schedule_with_warmup"
            ) as MockScheduler,
            patch("app.services.distillation_trainer.DataLoader") as MockDataLoader,
            patch("app.services.distillation_trainer.train_test_split") as mock_split,
            patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "ckpt")),
            patch("app.services.distillation_trainer.LOG_DIR", str(tmp_path / "logs")),
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockModel.from_pretrained.return_value = mock_model
            MockAdamW.return_value = MagicMock()
            MockScheduler.return_value = MagicMock()

            # Create mock data loaders
            mock_train_loader = MagicMock()
            mock_train_loader.__iter__ = MagicMock(return_value=iter([]))
            mock_train_loader.__len__ = MagicMock(return_value=1)
            mock_val_loader = MagicMock()
            mock_val_loader.__iter__ = MagicMock(return_value=iter([]))
            mock_val_loader.__len__ = MagicMock(return_value=1)

            MockDataLoader.side_effect = [mock_train_loader, mock_val_loader]

            # Split data
            texts = [f"t{i}" for i in range(25)]
            labels = [i % 5 for i in range(25)]
            mock_split.return_value = (texts[:20], texts[20:], labels[:20], labels[20:])

            # Mock train_epoch and evaluate
            trainer.train_epoch = MagicMock(return_value=(0.5, 0.8))
            trainer.evaluate = MagicMock(
                return_value={
                    "val_loss": 0.4,
                    "val_accuracy": 0.85,
                    "preds": [0, 1],
                    "labels": [0, 1],
                }
            )
            trainer.save_checkpoint = MagicMock()

            os.makedirs(str(tmp_path / "ckpt"), exist_ok=True)
            os.makedirs(str(tmp_path / "logs"), exist_ok=True)

            trainer.train(data_path, output_dir=str(tmp_path / "ckpt"))

            trainer.train_epoch.assert_called_once()
            trainer.evaluate.assert_called_once()
            # save_checkpoint called for last + best
            assert trainer.save_checkpoint.call_count == 2

    def test_train_logs_training_log(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", epochs=1, batch_size=2)

        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        log_dir = str(tmp_path / "logs")
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        trainer.load_data = MagicMock(return_value=(["a"] * 15, [0] * 15))
        trainer.prepare_data = MagicMock()
        trainer.train_epoch = MagicMock(return_value=(0.5, 0.8))
        trainer.evaluate = MagicMock(
            return_value={"val_loss": 0.4, "val_accuracy": 0.9, "preds": [0], "labels": [0]}
        )
        trainer.save_checkpoint = MagicMock()

        with (
            patch("app.services.distillation_trainer.AdamW", return_value=MagicMock()),
            patch(
                "app.services.distillation_trainer.get_linear_schedule_with_warmup",
                return_value=MagicMock(),
            ),
            patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir),
            patch("app.services.distillation_trainer.LOG_DIR", log_dir),
        ):
            trainer.train(data_path, output_dir=ckpt_dir)

        # Verify log file was created
        log_files = [f for f in os.listdir(log_dir) if f.startswith("training_log_")]
        assert len(log_files) == 1
        with open(os.path.join(log_dir, log_files[0])) as f:
            log_data = json.load(f)
        assert "best_accuracy" in log_data
        assert "best_epoch" in log_data
        assert log_data["best_accuracy"] == 0.9


class TestDistillationTrainerSaveCheckpointConfig:
    """测试 save_checkpoint 的配置内容。"""

    def test_config_contains_model_name(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", model_name="test-model")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=3, best=False)

        config_path = os.path.join(checkpoint_path, "train_config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["model_name"] == "test-model"
        assert config["epoch"] == 3
        assert config["best"] is False
        assert config["id2label"] == ID_TO_LABEL
        assert config["label2id"] == LABEL_TO_ID
        assert config["max_length"] == 64

    def test_vocab_json_contains_mappings(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=True)

        vocab_path = os.path.join(ckpt_dir, "vocab.json")
        with open(vocab_path, encoding="utf-8") as f:
            vocab = json.load(f)
        # Verify id2label values match INTENT_LABELS
        for idx, label in vocab["id2label"].items():
            assert INTENT_LABELS[int(idx)] == label
        # Verify label2id values match LABEL_TO_ID
        for label, idx in vocab["label2id"].items():
            assert LABEL_TO_ID[label] == idx
