# mypy: disable-error-code="attr-defined"
"""Shared torch/transformers stubs for tests/test_services/.

The source modules under test (app.services.intent_trainer,
app.services.distillation_trainer, app.services.train_intent) import
``torch`` and ``transformers`` at module top-level. These heavy ML deps are
intentionally excluded from the CI/test venv — see requirements-server-api.txt
which comments "与 XCAGI/requirements.txt 相比去掉 torch 等大包". Without these
stubs every test file that imports those modules skips via
``pytest.skip(allow_module_level=True)``, leaving the trainer code paths with
zero real coverage in CI.

This conftest installs torch / transformers stubs into sys.modules BEFORE any
test module in this directory is collected. Stubs are installed selectively —
if the real ``torch`` is importable (e.g. local dev venv has it installed),
the real library is kept and only the missing ``transformers`` is stubbed.
This preserves real-torch behavior for tests that depend on actual tensor
arithmetic (e.g. ``test_getitem_label_is_long_tensor`` checks ``.dtype``),
while still letting the source modules import in CI where neither is installed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from unittest.mock import MagicMock

_STUB_FLAG = "_xcmax_ml_stubs_installed"


def _is_importable(name: str) -> bool:
    """Check whether a module is really importable without side effects."""
    return importlib.util.find_spec(name) is not None


def _install_torch_stubs() -> None:
    """Install torch / torch.optim / torch.utils / torch.utils.data stubs.

    Uses real ``types.ModuleType`` stubs (not bare MagicMock) because
    sklearn/scipy introspect ``torch.Tensor`` via issubclass and a MagicMock
    attribute would trip ``issubclass``.
    """
    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)

    class _FakeTensor:
        def __init__(self, data=None):
            self._data = data
            self.dtype = "long"

        def squeeze(self, _dim=0):
            return self

        def item(self):
            if isinstance(self._data, (int, float)):
                return self._data
            return 0

        def to(self, _device):
            return self

        def cpu(self):
            return self

        def numpy(self):
            if isinstance(self._data, list):
                flat = []
                for x in self._data:
                    if isinstance(x, list):
                        flat.extend(x)
                    else:
                        flat.append(x)
                return flat if flat else [0]
            if isinstance(self._data, (int, float)):
                return [self._data]
            return [0]

        def size(self, _dim=0):
            return 1

        def backward(self):
            pass

        def __eq__(self, _other):
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
        return _FakeTensor([0])

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
        utils=types.SimpleNamespace(clip_grad_norm_=lambda *_a, **_k: None),
    )
    torch_mod.onnx = types.SimpleNamespace(export=lambda *_a, **_k: None)

    torch_optim = types.ModuleType("torch.optim")
    torch_optim.AdamW = MagicMock
    torch_mod.optim = torch_optim

    torch_utils = types.ModuleType("torch.utils")
    torch_utils_data = types.ModuleType("torch.utils.data")

    class _DatasetBase:
        def __init__(self, *_a, **_kw):
            pass

    torch_utils_data.Dataset = _DatasetBase
    torch_utils_data.DataLoader = MagicMock
    torch_mod.utils = torch_utils
    torch_utils.data = torch_utils_data

    sys.modules["torch"] = torch_mod
    sys.modules["torch.optim"] = torch_optim
    sys.modules["torch.utils"] = torch_utils
    sys.modules["torch.utils.data"] = torch_utils_data


def _install_transformers_stub() -> None:
    """Install a transformers stub. Uses real class stubs (not bare MagicMock)
    so that ``patch`` can find and replace class-level attributes like
    ``from_pretrained``."""
    transformers_mod = types.ModuleType("transformers")

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

    sys.modules["transformers"] = transformers_mod


def _install_torch_transformers_stubs() -> None:
    """Install stubs only for missing modules. If real torch is available
    (local dev venv), it is kept — only the missing transformers is stubbed.
    This preserves real-tensor behavior for tests that check ``.dtype`` etc.

    Set XCMAX_FORCE_ML_STUBS=1 to force stub install even if real torch is
    available — used to simulate the CI environment locally."""
    import os

    if getattr(sys, _STUB_FLAG, False):
        return

    force_stubs = os.environ.get("XCMAX_FORCE_ML_STUBS") == "1"
    torch_real = _is_importable("torch") and not force_stubs
    transformers_real = _is_importable("transformers") and not force_stubs

    if torch_real and transformers_real:
        setattr(sys, _STUB_FLAG, True)
        return

    if not torch_real:
        _install_torch_stubs()

    if not transformers_real:
        _install_transformers_stub()

    setattr(sys, _STUB_FLAG, True)


_install_torch_transformers_stubs()
