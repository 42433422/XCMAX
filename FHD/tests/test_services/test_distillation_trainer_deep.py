"""Deep coverage tests for app.services.distillation_trainer.

Root cause of near-zero coverage: the source module imports ``torch`` and
``transformers`` at module top-level. These heavy ML deps are NOT installed in
the CI/test venv, so the module fails to import and every existing test file
skips via ``pytest.skip(..., allow_module_level=True)`` — leaving the code
uncovered.

This file stubs out ``torch`` / ``transformers`` in ``sys.modules`` BEFORE
importing the source module, so the module body executes and the real code
paths (load_data, prepare_data, train_epoch, evaluate, save_checkpoint, train,
main) can be exercised. Only external boundaries (file I/O, the stubbed ML
libs) are mocked; the trainer's own logic runs for real.
"""

from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy ML deps so the source module can be imported without torch /
# transformers installed. We use real ``types.ModuleType`` stubs (not bare
# MagicMock) because sklearn/scipy introspect ``torch.Tensor`` via issubclass
# and a MagicMock attribute would trip ``issubclass``.
# ---------------------------------------------------------------------------


def _install_torch_transformers_stubs() -> None:
    if getattr(sys, "_xcmax_dt_stubs_installed", False):
        return

    torch_mod = types.ModuleType("torch")

    # torch.cuda
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)

    # torch.tensor — returns a fake tensor supporting .squeeze/.item/.to/.cpu/
    # .numpy/.size/.backward so existing tests that use torch.tensor(...) work.
    class _FakeTensor:
        def __init__(self, data=None):
            self._data = data

        def squeeze(self, _dim=0):
            return self

        def item(self):
            # Return the underlying scalar if it's a number, else 0
            if isinstance(self._data, (int, float)):
                return self._data
            return 0

        def to(self, _device):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return []

        def size(self, _dim=0):
            return 1

        def backward(self):
            pass

        def __eq__(self, other):
            return _FakeTensor()

        def sum(self):
            return _FakeTensor()

    def _tensor(data=None, *_a, **_kw):
        return _FakeTensor(data)

    torch_mod.tensor = _tensor
    torch_mod.Tensor = _FakeTensor
    torch_mod.zeros = lambda *_a, **_kw: _FakeTensor()
    torch_mod.ones = lambda *_a, **_kw: _FakeTensor()
    torch_mod.randn = lambda *_a, **_kw: _FakeTensor()
    torch_mod.long = "long"
    torch_mod.float = "float"

    def _argmax(*_args, **_kwargs):
        return _FakeTensor()

    torch_mod.argmax = _argmax

    # torch.no_grad — usable as @torch.no_grad() decorator (called with no args)
    class _NoGrad:
        def __call__(self, fn=None):
            if fn is None:
                return self
            def wrapper(*a, **kw):
                return fn(*a, **kw)
            return wrapper

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    torch_mod.no_grad = _NoGrad()

    # torch.nn.utils.clip_grad_norm_
    torch_mod.nn = types.SimpleNamespace(
        utils=types.SimpleNamespace(
            clip_grad_norm_=lambda *_a, **_k: None,
        ),
    )

    # torch.onnx.export
    torch_mod.onnx = types.SimpleNamespace(export=lambda *_a, **_k: None)

    # torch.utils.data.Dataset / DataLoader
    torch_utils = types.ModuleType("torch.utils")
    torch_utils_data = types.ModuleType("torch.utils.data")

    class _DatasetBase:
        def __init__(self, *_a, **_kw):
            pass

    torch_utils_data.Dataset = _DatasetBase
    torch_utils_data.DataLoader = MagicMock
    torch_mod.utils = torch_utils
    torch_utils.data = torch_utils_data

    transformers_mod = types.ModuleType("transformers")

    # Use real class stubs (not bare MagicMock) so that ``patch`` can find
    # and replace class-level attributes like ``from_pretrained``. If we used
    # ``MagicMock`` directly, ``patch("...AutoTokenizer.from_pretrained")``
    # would raise AttributeError because patch looks for the attribute on the
    # MagicMock *class*, not on instances.
    class _HFBase:
        @classmethod
        def from_pretrained(cls, *_a, **_kw):
            return MagicMock()

        @classmethod
        def save_pretrained(cls, *_a, **_kw):
            return None

    transformers_mod.AdamW = MagicMock
    transformers_mod.BertForSequenceClassification = _HFBase
    transformers_mod.BertTokenizer = _HFBase
    transformers_mod.get_linear_schedule_with_warmup = MagicMock
    transformers_mod.AutoConfig = _HFBase
    transformers_mod.AutoModelForSequenceClassification = _HFBase
    transformers_mod.AutoTokenizer = _HFBase
    transformers_mod.DataCollatorWithPadding = lambda *_a, **_kw: MagicMock()
    transformers_mod.EarlyStoppingCallback = MagicMock
    transformers_mod.Trainer = MagicMock
    transformers_mod.TrainingArguments = MagicMock

    sys.modules["torch"] = torch_mod
    sys.modules["torch.utils"] = torch_utils
    sys.modules["torch.utils.data"] = torch_utils_data
    sys.modules["transformers"] = transformers_mod
    sys._xcmax_dt_stubs_installed = True


_install_torch_transformers_stubs()

# Now safe to import the source module — its top-level imports will resolve
# against the stubs.
from app.services.distillation_trainer import (  # noqa: E402
    CHECKPOINT_DIR,
    DISTILL_DIR,
    ID_TO_LABEL,
    INTENT_LABELS,
    LABEL_TO_ID,
    LOG_DIR,
    DistillationDataset,
    DistillationTrainer,
    main,
)
import torch  # noqa: E402  (the stub)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jsonl(path, rows):
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _make_tsv(path, header, rows):
    parts = [header] + [f"{t}\t{l}" for t, l in rows]
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# DistillationDataset
# ---------------------------------------------------------------------------


class TestDistillationDatasetDeep:
    def test_len_matches_texts(self):
        tok = MagicMock()
        ds = DistillationDataset(["a", "b", "c"], [0, 1, 2], tok, max_length=8)
        assert len(ds) == 3

    def test_len_empty(self):
        ds = DistillationDataset([], [], MagicMock())
        assert len(ds) == 0

    def test_getitem_returns_expected_keys_and_calls_tokenizer(self):
        tok = MagicMock()
        tok.return_value = {
            "input_ids": MagicMock(),
            "attention_mask": MagicMock(),
        }
        # squeeze(0) must return the same mock so the dict values are usable
        tok.return_value["input_ids"].squeeze.return_value = "iid"
        tok.return_value["attention_mask"].squeeze.return_value = "amask"

        ds = DistillationDataset(["hello"], [3], tok, max_length=16)
        item = ds[0]

        assert set(item.keys()) == {"input_ids", "attention_mask", "labels"}
        assert item["input_ids"] == "iid"
        assert item["attention_mask"] == "amask"
        # Tokenizer called with the right args
        tok.assert_called_once_with(
            "hello",
            max_length=16,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

    def test_getitem_multiple_indices(self):
        tok = MagicMock()
        tok.return_value = {
            "input_ids": MagicMock(),
            "attention_mask": MagicMock(),
        }
        ds = DistillationDataset(["x", "y", "z"], [0, 5, 19], tok, max_length=4)
        _ = ds[0]
        _ = ds[1]
        _ = ds[2]
        assert tok.call_count == 3


# ---------------------------------------------------------------------------
# DistillationTrainer.__init__
# ---------------------------------------------------------------------------


class TestDistillationTrainerInitDeep:
    def test_default_hyperparameters(self):
        t = DistillationTrainer(device="cpu")
        assert t.model_name == "hfl/chinese-bert-wwm-ext"
        assert t.num_labels == len(INTENT_LABELS)
        assert t.max_length == 64
        assert t.learning_rate == 2e-5
        assert t.batch_size == 16
        assert t.epochs == 3
        assert t.warmup_ratio == 0.1
        assert t.device == "cpu"
        assert t.tokenizer is None
        assert t.model is None
        assert t.train_loader is None
        assert t.val_loader is None

    def test_explicit_device_cpu(self):
        t = DistillationTrainer(device="cpu")
        assert t.device == "cpu"

    def test_custom_hyperparameters(self):
        t = DistillationTrainer(
            model_name="custom/m",
            num_labels=5,
            max_length=128,
            learning_rate=1e-4,
            batch_size=8,
            epochs=7,
            warmup_ratio=0.2,
            device="cpu",
        )
        assert t.model_name == "custom/m"
        assert t.num_labels == 5
        assert t.max_length == 128
        assert t.learning_rate == 1e-4
        assert t.batch_size == 8
        assert t.epochs == 7
        assert t.warmup_ratio == 0.2

    def test_default_device_uses_cuda_availability(self):
        with patch("app.services.distillation_trainer.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            t = DistillationTrainer()
            assert t.device == "cpu"

    def test_default_device_cuda_when_available(self):
        with patch("app.services.distillation_trainer.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            t = DistillationTrainer()
            assert t.device == "cuda"


# ---------------------------------------------------------------------------
# DistillationTrainer.load_data — JSONL
# ---------------------------------------------------------------------------


class TestLoadDataJSONLDeep:
    def test_load_jsonl_valid(self, tmp_path):
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [
            {"text": "你好", "label": "greet"},
            {"text": "开单", "label": "shipment_generate"},
        ])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == ["你好", "开单"]
        assert labels == [LABEL_TO_ID["greet"], LABEL_TO_ID["shipment_generate"]]

    def test_load_jsonl_unknown_label_skipped(self, tmp_path):
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [
            {"text": "hi", "label": "greet"},
            {"text": "x", "label": "no_such_label"},
        ])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == ["hi"]
        assert labels == [LABEL_TO_ID["greet"]]

    def test_load_jsonl_missing_label_defaults_to_unk(self, tmp_path):
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [{"text": "something"}])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == ["something"]
        assert labels == [LABEL_TO_ID["unk"]]

    def test_load_jsonl_missing_text_defaults_to_empty(self, tmp_path):
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [{"label": "greet"}])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == [""]
        assert labels == [LABEL_TO_ID["greet"]]

    def test_load_jsonl_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == []
        assert labels == []


# ---------------------------------------------------------------------------
# DistillationTrainer.load_data — TSV
# ---------------------------------------------------------------------------


class TestLoadDataTSVDeep:
    def test_load_tsv_valid(self, tmp_path):
        path = tmp_path / "d.tsv"
        _make_tsv(path, "text\tlabel", [("你好", "greet"), ("开单", "shipment_generate")])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == ["你好", "开单"]
        assert labels == [LABEL_TO_ID["greet"], LABEL_TO_ID["shipment_generate"]]

    def test_load_tsv_skips_unknown_label(self, tmp_path):
        # Source appends text unconditionally, label only when valid.
        # So texts and labels can be out of sync for TSV.
        path = tmp_path / "d.tsv"
        _make_tsv(path, "text\tlabel", [("hi", "greet"), ("x", "unknown_label")])
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        # Both texts appended; only the valid label recorded
        assert texts == ["hi", "x"]
        assert labels == [LABEL_TO_ID["greet"]]

    def test_load_tsv_skips_single_column_lines(self, tmp_path):
        path = tmp_path / "d.tsv"
        path.write_text("text\tlabel\nonly_one_column\n你好\tgreet\n", encoding="utf-8")
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == ["你好"]
        assert labels == [LABEL_TO_ID["greet"]]

    def test_load_tsv_empty_after_header(self, tmp_path):
        path = tmp_path / "d.tsv"
        path.write_text("text\tlabel\n", encoding="utf-8")
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == []
        assert labels == []


# ---------------------------------------------------------------------------
# DistillationTrainer.load_data — unsupported format
# ---------------------------------------------------------------------------


class TestLoadDataUnsupportedDeep:
    def test_load_unsupported_format_returns_empty(self, tmp_path):
        path = tmp_path / "d.csv"
        path.write_text("text,label\nhi,greet\n", encoding="utf-8")
        t = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = t.load_data(str(path))
        assert texts == []
        assert labels == []


# ---------------------------------------------------------------------------
# DistillationTrainer.prepare_data
# ---------------------------------------------------------------------------


class TestPrepareDataDeep:
    def test_prepare_data_stratified_path(self):
        """When >=10 unique labels and >100 texts, stratified split is used."""
        texts = [f"text_{i}" for i in range(110)]
        labels = [i % 10 for i in range(110)]  # 10 unique labels

        t = DistillationTrainer(device="cpu")
        with patch("app.services.distillation_trainer.BertTokenizer") as mtok, \
             patch("app.services.distillation_trainer.BertForSequenceClassification") as mmodel, \
             patch("app.services.distillation_trainer.DataLoader") as mdl, \
             patch("app.services.distillation_trainer.train_test_split") as msplit:
            msplit.return_value = (texts[:88], texts[88:], labels[:88], labels[88:])
            mtok.from_pretrained.return_value = MagicMock()
            mmodel.from_pretrained.return_value = MagicMock()

            t.prepare_data(texts, labels, val_ratio=0.2)

            # stratify kwarg should be present (truthy list)
            _, kwargs = msplit.call_args
            assert kwargs.get("stratify") is not None
            assert t.tokenizer is not None
            assert t.model is not None
            assert t.train_loader is not None
            assert t.val_loader is not None
            t.model.to.assert_called_once_with("cpu")
            assert mdl.call_count == 2

    def test_prepare_data_non_stratified_path(self):
        """When <10 unique labels or <=100 texts, non-stratified split is used."""
        texts = [f"t{i}" for i in range(20)]
        labels = [i % 3 for i in range(20)]  # only 3 unique labels

        t = DistillationTrainer(device="cpu")
        with patch("app.services.distillation_trainer.BertTokenizer") as mtok, \
             patch("app.services.distillation_trainer.BertForSequenceClassification") as mmodel, \
             patch("app.services.distillation_trainer.DataLoader") as mdl, \
             patch("app.services.distillation_trainer.train_test_split") as msplit:
            msplit.return_value = (texts[:16], texts[16:], labels[:16], labels[16:])
            mtok.from_pretrained.return_value = MagicMock()
            mmodel.from_pretrained.return_value = MagicMock()

            t.prepare_data(texts, labels, val_ratio=0.2)

            _, kwargs = msplit.call_args
            # stratify should NOT be passed (or be None)
            assert "stratify" not in kwargs or kwargs["stratify"] is None

    def test_prepare_data_custom_val_ratio(self):
        texts = [f"t{i}" for i in range(20)]
        labels = [0] * 20

        t = DistillationTrainer(device="cpu")
        with patch("app.services.distillation_trainer.BertTokenizer") as mtok, \
             patch("app.services.distillation_trainer.BertForSequenceClassification") as mmodel, \
             patch("app.services.distillation_trainer.DataLoader"), \
             patch("app.services.distillation_trainer.train_test_split") as msplit:
            msplit.return_value = (texts[:10], texts[10:], labels[:10], labels[10:])
            mtok.from_pretrained.return_value = MagicMock()
            mmodel.from_pretrained.return_value = MagicMock()

            t.prepare_data(texts, labels, val_ratio=0.5)

            _, kwargs = msplit.call_args
            assert kwargs["test_size"] == 0.5
            assert kwargs["random_state"] == 42


# ---------------------------------------------------------------------------
# DistillationTrainer.train_epoch
# ---------------------------------------------------------------------------


class TestTrainEpochDeep:
    def test_train_epoch_single_batch(self):
        t = DistillationTrainer(device="cpu")

        # Use a simple namespace for batch values so .to() and arithmetic work
        class _Tensor:
            def __init__(self, val):
                self.val = val

            def to(self, _device):
                return self

            def size(self, dim=0):
                return 2

            def item(self):
                return self.val

            def backward(self):
                pass

            def __eq__(self, other):
                # preds == labels -> tensor of bools; .sum().item() -> 2
                return _Tensor(2)

            def sum(self):
                return _Tensor(2)

        labels = _Tensor(0)
        batch = {
            "input_ids": _Tensor(0),
            "attention_mask": _Tensor(0),
            "labels": labels,
        }

        mock_output = MagicMock()
        mock_output.loss = _Tensor(0.5)
        mock_output.logits = MagicMock()

        preds = _Tensor(0)  # torch.argmax result

        with patch("app.services.distillation_trainer.torch") as mock_torch:
            mock_torch.argmax.return_value = preds
            mock_torch.nn.utils.clip_grad_norm_ = MagicMock()
            t.model = MagicMock()
            t.model.return_value = mock_output
            t.model.parameters.return_value = iter([MagicMock()])
            t.train_loader = [batch]

            optimizer = MagicMock()
            scheduler = MagicMock()

            avg_loss, accuracy = t.train_epoch(optimizer, scheduler)

        assert avg_loss == 0.5
        assert accuracy == 1.0  # 2 correct / 2 total
        optimizer.zero_grad.assert_called_once()
        optimizer.step.assert_called_once()
        scheduler.step.assert_called_once()
        t.model.train.assert_called_once()

    def test_train_epoch_multiple_batches(self):
        t = DistillationTrainer(device="cpu")

        class _Tensor:
            def __init__(self, val, n=0):
                self.val = val
                self.n = n

            def to(self, _device):
                return self

            def size(self, dim=0):
                return self.n

            def item(self):
                return self.val

            def backward(self):
                pass

            def __eq__(self, other):
                return _Tensor(self.n, self.n)

            def sum(self):
                return _Tensor(self.n, self.n)

        def make_batch(n):
            return {
                "input_ids": _Tensor(0, n),
                "attention_mask": _Tensor(0, n),
                "labels": _Tensor(0, n),
            }

        b1 = make_batch(2)
        b2 = make_batch(3)

        mock_output = MagicMock()
        mock_output.loss = _Tensor(0.4, 0)
        mock_output.logits = MagicMock()

        with patch("app.services.distillation_trainer.torch") as mock_torch:
            mock_torch.argmax.side_effect = [_Tensor(0, 2), _Tensor(0, 3)]
            mock_torch.nn.utils.clip_grad_norm_ = MagicMock()
            t.model = MagicMock()
            t.model.return_value = mock_output
            t.model.parameters.return_value = iter([MagicMock()])
            t.train_loader = [b1, b2]

            optimizer = MagicMock()
            scheduler = MagicMock()
            avg_loss, accuracy = t.train_epoch(optimizer, scheduler)

        # (0.4 + 0.4) / 2 = 0.4 ; (2+3)/(2+3) = 1.0
        assert avg_loss == 0.4
        assert accuracy == 1.0
        assert optimizer.step.call_count == 2
        assert scheduler.step.call_count == 2


# ---------------------------------------------------------------------------
# DistillationTrainer.evaluate
# ---------------------------------------------------------------------------


class TestEvaluateDeep:
    def test_evaluate_returns_metrics(self):
        t = DistillationTrainer(device="cpu")

        class _Tensor:
            """Minimal fake tensor supporting .to/.cpu/.numpy/.item."""

            def __init__(self, val=0, numpy_val=None):
                self._val = val
                self._numpy = numpy_val if numpy_val is not None else [0, 1]

            def to(self, _device):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self._numpy

            def item(self):
                return self._val

        labels_tensor = _Tensor(0, numpy_val=[0, 1])
        batch = {
            "input_ids": _Tensor(0),
            "attention_mask": _Tensor(0),
            "labels": labels_tensor,
        }

        mock_output = MagicMock()
        mock_output.loss = _Tensor(0.3)
        mock_output.logits = MagicMock()

        preds_tensor = _Tensor(0, numpy_val=[0, 1])

        with patch("app.services.distillation_trainer.torch") as mock_torch, \
             patch("app.services.distillation_trainer.accuracy_score") as mock_acc:
            mock_torch.argmax.return_value = preds_tensor
            mock_torch.no_grad = MagicMock()
            mock_acc.return_value = 1.0

            t.model = MagicMock()
            t.model.return_value = mock_output
            t.val_loader = [batch]

            result = t.evaluate()

        assert result["val_loss"] == 0.3
        assert result["val_accuracy"] == 1.0
        assert result["preds"] == [0, 1]
        assert result["labels"] == [0, 1]
        t.model.eval.assert_called_once()


# ---------------------------------------------------------------------------
# DistillationTrainer.save_checkpoint
# ---------------------------------------------------------------------------


class TestSaveCheckpointDeep:
    def test_save_checkpoint_writes_config_and_vocab(self, tmp_path):
        t = DistillationTrainer(device="cpu")
        t.tokenizer = MagicMock()
        t.model = MagicMock()

        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir()

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(ckpt_dir)):
            t.save_checkpoint(str(ckpt), epoch=2, best=True)

        # model & tokenizer saved to ckpt path
        t.model.save_pretrained.assert_called_once_with(str(ckpt))
        t.tokenizer.save_pretrained.assert_called_once_with(str(ckpt))

        # train_config.json
        cfg_path = ckpt / "train_config.json"
        assert cfg_path.exists()
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["epoch"] == 2
        assert cfg["best"] is True
        assert cfg["model_name"] == t.model_name
        assert cfg["num_labels"] == t.num_labels
        assert cfg["max_length"] == t.max_length
        # JSON serializes int keys as strings
        assert cfg["id2label"] == {str(k): v for k, v in ID_TO_LABEL.items()}
        assert cfg["label2id"] == LABEL_TO_ID
        assert "saved_at" in cfg

        # vocab.json written to CHECKPOINT_DIR
        vocab_path = ckpt_dir / "vocab.json"
        assert vocab_path.exists()
        vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
        assert "id2label" in vocab
        assert "label2id" in vocab

    def test_save_checkpoint_best_false(self, tmp_path):
        t = DistillationTrainer(device="cpu")
        t.tokenizer = MagicMock()
        t.model = MagicMock()

        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir()

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(ckpt_dir)):
            t.save_checkpoint(str(ckpt), epoch=1, best=False)

        cfg = json.loads((ckpt / "train_config.json").read_text(encoding="utf-8"))
        assert cfg["best"] is False
        assert cfg["epoch"] == 1


# ---------------------------------------------------------------------------
# DistillationTrainer.train — orchestration
# ---------------------------------------------------------------------------


class TestTrainOrchestrationDeep:
    def test_train_returns_early_when_insufficient_data(self, tmp_path):
        """Fewer than 10 samples -> logs error and returns None."""
        path = tmp_path / "small.jsonl"
        _make_jsonl(path, [{"text": f"t{i}", "label": "greet"} for i in range(5)])

        t = DistillationTrainer(device="cpu", epochs=1)
        result = t.train(str(path), output_dir=str(tmp_path / "out"))
        assert result is None

    def test_train_full_flow_with_mocked_steps(self, tmp_path):
        """train() orchestrates load_data -> prepare_data -> epoch loop."""
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [{"text": f"t{i}", "label": "greet"} for i in range(15)])

        ckpt_dir = tmp_path / "ckpt"
        log_dir = tmp_path / "logs"
        ckpt_dir.mkdir()
        log_dir.mkdir()

        t = DistillationTrainer(device="cpu", epochs=1)

        # Mock the heavy steps but keep train() orchestration real
        t.prepare_data = MagicMock()
        t.train_epoch = MagicMock(return_value=(0.5, 0.8))
        t.evaluate = MagicMock(return_value={
            "val_loss": 0.4,
            "val_accuracy": 0.9,
            "preds": [0, 1],
            "labels": [0, 1],
        })
        t.save_checkpoint = MagicMock()
        t.tokenizer = MagicMock()
        t.model = MagicMock()
        t.train_loader = [MagicMock()]
        t.val_loader = [MagicMock()]
        t.model.parameters.return_value = iter([MagicMock()])

        with patch("app.services.distillation_trainer.AdamW") as mock_adamw, \
             patch("app.services.distillation_trainer.get_linear_schedule_with_warmup") as mock_sched, \
             patch("app.services.distillation_trainer.classification_report") as mock_report, \
             patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(ckpt_dir)), \
             patch("app.services.distillation_trainer.LOG_DIR", str(log_dir)):
            mock_adamw.return_value = MagicMock()
            mock_sched.return_value = MagicMock()
            mock_report.return_value = "report"

            t.train(str(path), output_dir=str(ckpt_dir))

        t.prepare_data.assert_called_once()
        t.train_epoch.assert_called_once()
        t.evaluate.assert_called_once()
        # save_checkpoint called for "last" + "best" (since 0.9 > 0)
        assert t.save_checkpoint.call_count == 2

        # training log written
        logs = [f for f in os.listdir(log_dir) if f.startswith("training_log_")]
        assert len(logs) == 1
        log_data = json.loads((log_dir / logs[0]).read_text(encoding="utf-8"))
        assert log_data["best_accuracy"] == 0.9
        assert log_data["best_epoch"] == 1
        assert log_data["total_epochs"] == 1

    def test_train_no_best_when_accuracy_zero(self, tmp_path):
        """When val_accuracy stays 0, best_checkpoint is never saved (only last)."""
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [{"text": f"t{i}", "label": "greet"} for i in range(15)])

        ckpt_dir = tmp_path / "ckpt"
        log_dir = tmp_path / "logs"
        ckpt_dir.mkdir()
        log_dir.mkdir()

        t = DistillationTrainer(device="cpu", epochs=1)
        t.prepare_data = MagicMock()
        t.train_epoch = MagicMock(return_value=(0.5, 0.0))
        t.evaluate = MagicMock(return_value={
            "val_loss": 0.4,
            "val_accuracy": 0.0,
            "preds": [0],
            "labels": [1],
        })
        t.save_checkpoint = MagicMock()
        t.tokenizer = MagicMock()
        t.model = MagicMock()
        t.train_loader = [MagicMock()]
        t.val_loader = [MagicMock()]
        t.model.parameters.return_value = iter([MagicMock()])

        with patch("app.services.distillation_trainer.AdamW", return_value=MagicMock()), \
             patch("app.services.distillation_trainer.get_linear_schedule_with_warmup", return_value=MagicMock()), \
             patch("app.services.distillation_trainer.classification_report", return_value="r"), \
             patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(ckpt_dir)), \
             patch("app.services.distillation_trainer.LOG_DIR", str(log_dir)):
            t.train(str(path), output_dir=str(ckpt_dir))

        # Only "last" checkpoint saved (best_accuracy stays 0, 0.0 > 0 is False)
        assert t.save_checkpoint.call_count == 1


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMainCLIDeep:
    def test_main_nonexistent_data_returns(self, caplog):
        with patch("sys.argv", ["distillation_trainer", "--data", "/no/such/file.jsonl"]):
            main()  # should log error and return

    def test_main_default_data_path_nonexistent(self, tmp_path):
        fake_default = str(tmp_path / "default.jsonl")
        with patch("sys.argv", ["distillation_trainer"]), \
             patch(
                 "app.services.distillation_trainer.get_distillation_training_data_path",
                 return_value=fake_default,
             ):
            main()

    def test_main_invokes_trainer_train(self, tmp_path):
        path = tmp_path / "d.jsonl"
        _make_jsonl(path, [{"text": f"t{i}", "label": "greet"} for i in range(15)])
        out_dir = str(tmp_path / "out")

        with patch("sys.argv", [
            "distillation_trainer",
            "--data", str(path),
            "--output", out_dir,
            "--epochs", "1",
            "--batch_size", "8",
            "--lr", "0.001",
            "--max_length", "32",
            "--model", "custom-model",
        ]), patch(
            "app.services.distillation_trainer.DistillationTrainer"
        ) as mock_cls:
            mock_inst = MagicMock()
            mock_cls.return_value = mock_inst
            main()

            _, kwargs = mock_cls.call_args
            assert kwargs["model_name"] == "custom-model"
            assert kwargs["max_length"] == 32
            assert kwargs["learning_rate"] == 0.001
            assert kwargs["batch_size"] == 8
            assert kwargs["epochs"] == 1
            mock_inst.train.assert_called_once_with(
                data_path=str(path), output_dir=out_dir
            )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstantsDeep:
    def test_intent_labels_count(self):
        assert len(INTENT_LABELS) == 20

    def test_label_to_id_bijective(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_unk_is_last(self):
        assert LABEL_TO_ID["unk"] == len(INTENT_LABELS) - 1

    def test_dirs_are_strings(self):
        assert isinstance(DISTILL_DIR, str)
        assert isinstance(CHECKPOINT_DIR, str)
        assert isinstance(LOG_DIR, str)
