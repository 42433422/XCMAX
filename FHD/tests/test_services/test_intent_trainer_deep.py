"""Deep coverage tests for app.services.intent_trainer.

Root cause of near-zero coverage: the source module imports ``torch`` and
``transformers`` at module top-level. These heavy ML deps are NOT installed in
the CI/test venv, so the module fails to import and every existing test file
skips via ``pytest.skip(..., allow_module_level=True)`` — leaving the code
uncovered.

This file stubs out ``torch`` / ``transformers`` in ``sys.modules`` BEFORE
importing the source module, so the module body executes and the real code
paths (parse_nlu_yaml, load_training_data, split_data, compute_metrics,
train_intent_model, export_to_onnx, main) can be exercised. Only external
boundaries (file I/O, the stubbed ML libs, onnxruntime) are mocked; the
trainer's own logic runs for real.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy ML deps so the source module can be imported without torch /
# transformers installed. We use real ``types.ModuleType`` stubs (not bare
# MagicMock) because sklearn/scipy introspect ``torch.Tensor`` via issubclass
# and a MagicMock attribute would trip ``issubclass``.
# ---------------------------------------------------------------------------


def _install_torch_transformers_stubs() -> None:
    if getattr(sys, "_xcmax_it_stubs_installed", False):
        return

    torch_mod = types.ModuleType("torch")
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
    torch_mod.nn = types.SimpleNamespace(
        utils=types.SimpleNamespace(
            clip_grad_norm_=lambda *_a, **_k: None,
        ),
    )
    torch_mod.onnx = types.SimpleNamespace(export=lambda *_a, **_k: None)

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
    sys._xcmax_it_stubs_installed = True


_install_torch_transformers_stubs()

# Now safe to import the source module.
from app.services.intent_trainer import (  # noqa: E402
    HAS_YAML,
    ID_TO_LABEL,
    INTENT_LABELS,
    LABEL_TO_ID,
    IntentDataset,
    IntentExample,
    compute_metrics,
    export_to_onnx,
    load_training_data,
    main,
    parse_nlu_yaml,
    split_data,
    train_intent_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path, content):
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# IntentExample dataclass
# ---------------------------------------------------------------------------


class TestIntentExampleDeep:
    def test_create(self):
        ex = IntentExample(text="你好", label="greet")
        assert ex.text == "你好"
        assert ex.label == "greet"

    def test_equality(self):
        a = IntentExample(text="hi", label="greet")
        b = IntentExample(text="hi", label="greet")
        assert a == b

    def test_field_assignment(self):
        ex = IntentExample(text="x", label="y")
        ex.text = "changed"
        assert ex.text == "changed"


# ---------------------------------------------------------------------------
# IntentDataset
# ---------------------------------------------------------------------------


class TestIntentDatasetDeep:
    def test_len_matches_examples(self):
        tok = MagicMock()
        ds = IntentDataset(
            [IntentExample("a", "greet"), IntentExample("b", "help")],
            tok,
        )
        assert len(ds) == 2

    def test_len_empty(self):
        ds = IntentDataset([], MagicMock())
        assert len(ds) == 0

    def test_getitem_with_known_label(self):
        tok = MagicMock()
        # encoding is a dict of {key: tensor-with-squeeze}
        mock_input = MagicMock()
        mock_input.squeeze.return_value = "iid"
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = "amask"
        tok.return_value = {"input_ids": mock_input, "attention_mask": mock_attn}

        ds = IntentDataset([IntentExample("hello", "greet")], tok, max_length=16)
        item = ds[0]

        assert item["input_ids"] == "iid"
        assert item["attention_mask"] == "amask"
        # label tensor created via torch.tensor(LABEL_TO_ID[...])
        assert "labels" in item
        tok.assert_called_once_with(
            "hello",
            max_length=16,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

    def test_getitem_with_unknown_label_no_labels_key(self):
        tok = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = "iid"
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = "amask"
        tok.return_value = {"input_ids": mock_input, "attention_mask": mock_attn}

        ds = IntentDataset([IntentExample("x", "no_such_label")], tok)
        item = ds[0]
        # Unknown label -> "labels" key absent
        assert "labels" not in item

    def test_getitem_multiple(self):
        tok = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = "iid"
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = "amask"
        tok.return_value = {"input_ids": mock_input, "attention_mask": mock_attn}

        ds = IntentDataset(
            [IntentExample("a", "greet"), IntentExample("b", "help")],
            tok,
        )
        _ = ds[0]
        _ = ds[1]
        assert tok.call_count == 2


# ---------------------------------------------------------------------------
# parse_nlu_yaml
# ---------------------------------------------------------------------------


class TestParseNluYamlDeep:
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_single_intent_multiple_examples(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
    - 你好
    - 嗨
    - 早
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 3
        assert all(r.label == "greet" for r in result)
        assert result[0].text == "你好"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_multiple_intents(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
    - 你好
- intent: goodbye
  examples: |
    - 再见
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 2
        labels = {r.label for r in result}
        assert labels == {"greet", "goodbye"}

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_negation_test_renamed_to_negation(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: negation_test
  examples: |
    - 不要
    - 不需要
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 2
        assert all(r.label == "negation" for r in result)

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_examples(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
""")
        result = parse_nlu_yaml(str(path))
        assert result == []

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_item_without_intent_key_skipped(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- something_else: value
- intent: greet
  examples: |
    - hi
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 1
        assert result[0].label == "greet"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_item_without_examples_key_skipped(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
- intent: goodbye
  examples: |
    - bye
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 1
        assert result[0].label == "goodbye"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_text_after_dash_skipped(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
    - 你好
    -
    - 嗨
""")
        result = parse_nlu_yaml(str(path))
        assert len(result) == 2
        assert result[0].text == "你好"
        assert result[1].text == "嗨"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_no_nlu_key(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
other_key: value
""")
        result = parse_nlu_yaml(str(path))
        assert result == []

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_nlu_list(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, "nlu: []\n")
        result = parse_nlu_yaml(str(path))
        assert result == []

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_line_without_dash_skipped(self, tmp_path):
        path = tmp_path / "nlu.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
    你好
    - 嗨
""")
        result = parse_nlu_yaml(str(path))
        # Only the line starting with "-" is picked up
        assert len(result) == 1
        assert result[0].text == "嗨"

    def test_parse_nlu_yaml_raises_when_yaml_not_installed(self, tmp_path):
        """When HAS_YAML is False, parse_nlu_yaml raises ImportError."""
        path = tmp_path / "nlu.yml"
        path.write_text("nlu: []\n", encoding="utf-8")
        with patch("app.services.intent_trainer.HAS_YAML", False):
            with pytest.raises(ImportError, match="PyYAML is required"):
                parse_nlu_yaml(str(path))


# ---------------------------------------------------------------------------
# load_training_data
# ---------------------------------------------------------------------------


class TestLoadTrainingDataDeep:
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_yml(self, tmp_path):
        path = tmp_path / "data.yml"
        _write_yaml(path, """
nlu:
- intent: greet
  examples: |
    - 你好
""")
        result = load_training_data(str(path))
        assert len(result) == 1
        assert result[0].label == "greet"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_yaml_extension(self, tmp_path):
        path = tmp_path / "data.yaml"
        _write_yaml(path, """
nlu:
- intent: help
  examples: |
    - 帮助
""")
        result = load_training_data(str(path))
        assert len(result) == 1
        assert result[0].label == "help"

    def test_load_json_valid(self, tmp_path):
        path = tmp_path / "data.json"
        _write_json(path, [
            {"text": "你好", "label": "greet"},
            {"text": "再见", "label": "goodbye"},
        ])
        result = load_training_data(str(path))
        assert len(result) == 2
        assert result[0].text == "你好"
        assert result[1].label == "goodbye"

    def test_load_json_empty_list(self, tmp_path):
        path = tmp_path / "data.json"
        _write_json(path, [])
        result = load_training_data(str(path))
        assert result == []

    def test_load_json_missing_fields_skipped(self, tmp_path):
        path = tmp_path / "data.json"
        _write_json(path, [{"text": "hi"}, {"label": "greet"}, {"text": "x", "label": "greet"}])
        result = load_training_data(str(path))
        assert len(result) == 1
        assert result[0].text == "x"

    def test_load_json_with_extra_fields(self, tmp_path):
        path = tmp_path / "data.json"
        _write_json(path, [{"text": "hi", "label": "greet", "extra": "ignored"}])
        result = load_training_data(str(path))
        assert len(result) == 1

    def test_load_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("text,label\nhi,greet", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported data format"):
            load_training_data(str(path))


# ---------------------------------------------------------------------------
# split_data
# ---------------------------------------------------------------------------


class TestSplitDataDeep:
    def test_default_ratios(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(100)]
        train, val, test = split_data(examples)
        assert len(train) == 80
        assert len(val) == 10
        assert len(test) == 10

    def test_custom_ratios(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(100)]
        train, val, test = split_data(examples, train_ratio=0.7, val_ratio=0.2, test_ratio=0.1)
        assert len(train) == 70
        assert len(val) == 20
        assert len(test) == 10

    def test_total_preserved(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(30)]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 30

    def test_empty(self):
        train, val, test = split_data([])
        assert train == []
        assert val == []
        assert test == []

    def test_single_example(self):
        examples = [IntentExample("x", "greet")]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 1

    def test_reproducible_with_same_seed(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(50)]
        t1, v1, te1 = split_data(examples, seed=42)
        t2, v2, te2 = split_data(examples, seed=42)
        assert [e.text for e in t1] == [e.text for e in t2]
        assert [e.text for e in v1] == [e.text for e in v2]
        assert [e.text for e in te1] == [e.text for e in te2]

    def test_different_seed_different_order(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(50)]
        t1, _, _ = split_data(examples, seed=42)
        t2, _, _ = split_data(examples, seed=99)
        assert [e.text for e in t1] != [e.text for e in t2]

    def test_does_not_mutate_input(self):
        examples = [IntentExample(f"t{i}", "greet") for i in range(20)]
        original = list(examples)
        split_data(examples)
        assert examples == original


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


class TestComputeMetricsDeep:
    def test_perfect_predictions(self):
        import numpy as np

        result = compute_metrics((np.array([[0.9, 0.1], [0.1, 0.9]]), np.array([0, 1])))
        assert result["accuracy"] == 1.0
        assert result["f1"] == 1.0
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0

    def test_all_wrong(self):
        import numpy as np

        result = compute_metrics((np.array([[0.1, 0.9], [0.9, 0.1]]), np.array([0, 1])))
        assert result["accuracy"] == 0.0

    def test_partial(self):
        import numpy as np

        result = compute_metrics((
            np.array([[0.9, 0.1], [0.1, 0.9], [0.8, 0.2]]),
            np.array([0, 1, 1]),
        ))
        assert 0 < result["accuracy"] < 1

    def test_multiclass(self):
        import numpy as np

        logits = np.array([
            [0.8, 0.1, 0.1],
            [0.1, 0.8, 0.1],
            [0.1, 0.1, 0.8],
        ])
        labels = np.array([0, 1, 2])
        result = compute_metrics((logits, labels))
        assert result["accuracy"] == 1.0

    def test_single_class(self):
        import numpy as np

        result = compute_metrics((np.array([[0.9, 0.1], [0.8, 0.2]]), np.array([0, 0])))
        assert result["accuracy"] == 1.0
        assert "precision" in result
        assert "recall" in result
        assert "f1" in result

    def test_returns_dict_with_expected_keys(self):
        import numpy as np

        result = compute_metrics((np.array([[0.9, 0.1]]), np.array([0])))
        assert set(result.keys()) == {"accuracy", "precision", "recall", "f1"}


# ---------------------------------------------------------------------------
# train_intent_model
# ---------------------------------------------------------------------------


class TestTrainIntentModelDeep:
    def test_empty_data_raises_value_error(self, tmp_path):
        with patch("app.services.intent_trainer.load_training_data", return_value=[]):
            with pytest.raises(ValueError, match="训练数据为空"):
                train_intent_model(data_path="fake.json", output_dir=str(tmp_path / "out"))

    @patch("app.services.intent_trainer.DataCollatorWithPadding")
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification")
    @patch("app.services.intent_trainer.AutoConfig")
    @patch("app.services.intent_trainer.AutoTokenizer")
    @patch("app.services.intent_trainer.load_training_data")
    def test_full_training_flow(
        self,
        mock_load,
        mock_tok,
        mock_config,
        mock_model_cls,
        mock_trainer_cls,
        mock_dcp,
        tmp_path,
    ):
        mock_load.return_value = [
            IntentExample(f"t{i}", "greet") for i in range(20)
        ]
        mock_tok.from_pretrained.return_value = MagicMock()
        mock_config.from_pretrained.return_value = MagicMock()
        mock_model_cls.from_pretrained.return_value = MagicMock()
        mock_dcp.return_value = MagicMock()

        mock_trainer = MagicMock()
        mock_trainer.evaluate.return_value = {"eval_loss": 0.5, "eval_f1": 0.9}

        # save_model must create the target dir so the subsequent open() works
        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer.save_model.side_effect = _save_model
        mock_trainer_cls.return_value = mock_trainer

        out_dir = tmp_path / "out"
        result = train_intent_model(
            data_path="fake.json",
            output_dir=str(out_dir),
            num_epochs=1,
            batch_size=4,
        )

        # Trainer.train() and evaluate() called
        mock_trainer.train.assert_called_once()
        mock_trainer.evaluate.assert_called_once()
        # Model saved
        mock_trainer.save_model.assert_called_once()
        # Result is the final model path
        assert "final" in str(result)
        # intent_labels.json written
        labels_file = Path(result) / "intent_labels.json"
        assert labels_file.exists()
        labels_data = json.loads(labels_file.read_text(encoding="utf-8"))
        assert labels_data["labels"] == INTENT_LABELS

    @patch("app.services.intent_trainer.DataCollatorWithPadding")
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification")
    @patch("app.services.intent_trainer.AutoConfig")
    @patch("app.services.intent_trainer.AutoTokenizer")
    @patch("app.services.intent_trainer.load_training_data")
    def test_early_stopping_disabled_when_patience_zero(
        self,
        mock_load,
        mock_tok,
        mock_config,
        mock_model_cls,
        mock_trainer_cls,
        mock_dcp,
        tmp_path,
    ):
        mock_load.return_value = [IntentExample(f"t{i}", "greet") for i in range(20)]
        mock_tok.from_pretrained.return_value = MagicMock()
        mock_config.from_pretrained.return_value = MagicMock()
        mock_model_cls.from_pretrained.return_value = MagicMock()
        mock_dcp.return_value = MagicMock()
        mock_trainer = MagicMock()

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer.save_model.side_effect = _save_model
        mock_trainer_cls.return_value = mock_trainer

        with patch("app.services.intent_trainer.EarlyStoppingCallback") as mock_es:
            train_intent_model(
                data_path="fake.json",
                output_dir=str(tmp_path / "out"),
                num_epochs=1,
                early_stopping_patience=0,
            )
            # EarlyStoppingCallback should NOT be instantiated
            mock_es.assert_not_called()

    @patch("app.services.intent_trainer.DataCollatorWithPadding")
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification")
    @patch("app.services.intent_trainer.AutoConfig")
    @patch("app.services.intent_trainer.AutoTokenizer")
    @patch("app.services.intent_trainer.load_training_data")
    def test_early_stopping_enabled_when_patience_positive(
        self,
        mock_load,
        mock_tok,
        mock_config,
        mock_model_cls,
        mock_trainer_cls,
        mock_dcp,
        tmp_path,
    ):
        mock_load.return_value = [IntentExample(f"t{i}", "greet") for i in range(20)]
        mock_tok.from_pretrained.return_value = MagicMock()
        mock_config.from_pretrained.return_value = MagicMock()
        mock_model_cls.from_pretrained.return_value = MagicMock()
        mock_dcp.return_value = MagicMock()
        mock_trainer = MagicMock()

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer.save_model.side_effect = _save_model
        mock_trainer_cls.return_value = mock_trainer

        with patch("app.services.intent_trainer.EarlyStoppingCallback") as mock_es:
            train_intent_model(
                data_path="fake.json",
                output_dir=str(tmp_path / "out"),
                num_epochs=1,
                early_stopping_patience=3,
            )
            mock_es.assert_called_once_with(early_stopping_patience=3)

    @patch("app.services.intent_trainer.DataCollatorWithPadding")
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification")
    @patch("app.services.intent_trainer.AutoConfig")
    @patch("app.services.intent_trainer.AutoTokenizer")
    @patch("app.services.intent_trainer.load_training_data")
    def test_output_dir_created(
        self,
        mock_load,
        mock_tok,
        mock_config,
        mock_model_cls,
        mock_trainer_cls,
        mock_dcp,
        tmp_path,
    ):
        mock_load.return_value = [IntentExample(f"t{i}", "greet") for i in range(20)]
        mock_tok.from_pretrained.return_value = MagicMock()
        mock_config.from_pretrained.return_value = MagicMock()
        mock_model_cls.from_pretrained.return_value = MagicMock()
        mock_dcp.return_value = MagicMock()
        mock_trainer = MagicMock()

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer.save_model.side_effect = _save_model
        mock_trainer_cls.return_value = mock_trainer

        out_dir = tmp_path / "nested" / "out"
        train_intent_model(
            data_path="fake.json",
            output_dir=str(out_dir),
            num_epochs=1,
        )
        assert out_dir.exists()


# ---------------------------------------------------------------------------
# export_to_onnx
# ---------------------------------------------------------------------------


class TestExportToOnnxDeep:
    def test_skips_when_onnxruntime_not_installed(self, tmp_path):
        """When onnxruntime import fails, export_to_onnx returns None silently."""
        with patch.dict("sys.modules", {"onnxruntime": None}):
            # Force ImportError by setting to None
            result = export_to_onnx(str(tmp_path), str(tmp_path / "model.onnx"))
            assert result is None

    @patch("app.services.intent_trainer.torch.onnx.export")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification")
    @patch("app.services.intent_trainer.AutoTokenizer")
    def test_exports_when_onnxruntime_available(
        self,
        mock_tok,
        mock_model_cls,
        mock_onnx_export,
        tmp_path,
    ):
        mock_tok_inst = MagicMock()
        mock_tok.from_pretrained.return_value = mock_tok_inst
        mock_model = MagicMock()
        mock_model_cls.from_pretrained.return_value = mock_model

        # Make onnxruntime importable
        import sys

        fake_onnxruntime = MagicMock()
        with patch.dict(sys.modules, {"onnxruntime": fake_onnxruntime}):
            out_path = str(tmp_path / "model.onnx")
            export_to_onnx(str(tmp_path), out_path)

            mock_tok.from_pretrained.assert_called_once_with(str(tmp_path))
            mock_model_cls.from_pretrained.assert_called_once_with(str(tmp_path))
            mock_model.eval.assert_called_once()
            mock_onnx_export.assert_called_once()
            # Verify output_path passed
            _, kwargs = mock_onnx_export.call_args
            assert kwargs.get("output_names") == ["logits"]


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMainCLIDeep:
    def test_main_requires_data_arg_exits(self):
        with patch("sys.argv", ["intent_trainer"]):
            with pytest.raises(SystemExit):
                main()

    @patch("app.services.intent_trainer.train_intent_model")
    def test_main_calls_train(self, mock_train, tmp_path):
        mock_train.return_value = str(tmp_path / "final")
        with patch("sys.argv", [
            "intent_trainer",
            "--data", "fake.json",
            "--epochs", "2",
            "--batch_size", "8",
            "--lr", "0.001",
            "--max_length", "128",
            "--model", "custom-model",
            "--output", str(tmp_path / "out"),
        ]):
            main()

            _, kwargs = mock_train.call_args
            assert kwargs["data_path"] == "fake.json"
            assert kwargs["model_name"] == "custom-model"
            assert kwargs["output_dir"] == str(tmp_path / "out")
            assert kwargs["num_epochs"] == 2
            assert kwargs["batch_size"] == 8
            assert kwargs["learning_rate"] == 0.001
            assert kwargs["max_length"] == 128

    @patch("app.services.intent_trainer.export_to_onnx")
    @patch("app.services.intent_trainer.train_intent_model")
    def test_main_with_export_onnx_flag(self, mock_train, mock_export, tmp_path):
        mock_train.return_value = str(tmp_path / "final")
        with patch("sys.argv", [
            "intent_trainer",
            "--data", "fake.json",
            "--epochs", "1",
            "--export_onnx",
            "--output", str(tmp_path / "out"),
        ]):
            main()

            mock_train.assert_called_once()
            mock_export.assert_called_once()
            # export_to_onnx called with model_path, onnx_path, max_length
            args, _ = mock_export.call_args
            assert args[0] == str(tmp_path / "final")
            assert args[1].endswith("model.onnx")

    @patch("app.services.intent_trainer.export_to_onnx")
    @patch("app.services.intent_trainer.train_intent_model")
    def test_main_without_export_onnx_flag(self, mock_train, mock_export, tmp_path):
        mock_train.return_value = str(tmp_path / "final")
        with patch("sys.argv", [
            "intent_trainer",
            "--data", "fake.json",
            "--epochs", "1",
        ]):
            main()

            mock_train.assert_called_once()
            mock_export.assert_not_called()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstantsDeep:
    def test_labels_count(self):
        assert len(INTENT_LABELS) == 20

    def test_label_to_id_bijective(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_id_to_label_contiguous(self):
        assert sorted(ID_TO_LABEL.keys()) == list(range(len(INTENT_LABELS)))

    def test_unk_is_last(self):
        assert INTENT_LABELS[-1] == "unk"
        assert LABEL_TO_ID["unk"] == len(INTENT_LABELS) - 1

    def test_known_intents_present(self):
        for intent in ("shipment_generate", "customers", "greet", "help", "unk"):
            assert intent in LABEL_TO_ID

    def test_has_yaml_is_bool(self):
        assert isinstance(HAS_YAML, bool)
