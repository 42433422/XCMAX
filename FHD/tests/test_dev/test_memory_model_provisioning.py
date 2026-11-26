"""Release models must be authenticated before ONNX or tokenizer construction."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def provisioner(tmp_path, monkeypatch):
    source = Path(__file__).parents[2] / "scripts/dev/provision_memory_model.py"
    spec = importlib.util.spec_from_file_location("pinned_memory_provisioner", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    downloaded = tmp_path / "downloaded"
    downloaded.mkdir()
    content = b"trusted test model bytes"
    (downloaded / "model_optimized.onnx").write_bytes(content)
    monkeypatch.setattr(
        module, "MODEL_HASHES", {"model_optimized.onnx": hashlib.sha256(content).hexdigest()}
    )
    download = Mock(return_value=str(downloaded))
    embedder = Mock(return_value=SimpleNamespace(embed=lambda _: [[1.0, 2.0]]))
    monkeypatch.setattr("huggingface_hub.snapshot_download", download)
    monkeypatch.setattr("fastembed.TextEmbedding", embedder)
    return module, download, embedder


def test_provision_pins_upstream_revision_and_loads_verified_bytes_offline(tmp_path, provisioner):
    module, download, embedder = provisioner
    root = tmp_path / "release"
    manifest = module.provision(root)
    assert manifest["revision"] == module.MODEL_REVISION
    assert manifest["dimensions"] == 2
    assert download.call_args.kwargs["revision"] == module.MODEL_REVISION
    assert download.call_args.kwargs["repo_id"] == module.MODEL_REPO
    assert set(download.call_args.kwargs["allow_patterns"]) == set(module.MODEL_HASHES)
    assert all(call.kwargs["local_files_only"] for call in embedder.call_args_list)


def test_untrusted_download_is_rejected_before_native_parser(tmp_path, provisioner):
    module, download, embedder = provisioner
    (Path(download.return_value) / "model_optimized.onnx").write_bytes(b"substituted model")
    with pytest.raises(ValueError, match="pinned model file hash mismatch"):
        module.provision(tmp_path / "release")
    embedder.assert_not_called()


@pytest.mark.parametrize("tamper", ["weights", "revision"])
def test_regenerated_manifest_cannot_authorize_tampered_cache(tmp_path, provisioner, tamper):
    module, _, embedder = provisioner
    root = tmp_path / "release"
    manifest = module.provision(root)
    snapshot = module.pinned_model_dir(root)
    if tamper == "weights":
        (snapshot / "model_optimized.onnx").write_bytes(b"untrusted weights")
    else:
        (snapshot.parent.parent / "refs/main").write_text("untrusted-revision")
    manifest["sha256"] = module.artifact_digest(root)
    (root / module.MANIFEST).write_text(json.dumps(manifest))
    embedder.reset_mock()
    with pytest.raises(ValueError, match="mismatch"):
        module.verify(root)
    embedder.assert_not_called()
