"""The sole LangGraph runtime copy remains reproducible after snapshot removal."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["xcagi_langgraph_core", "xcagi_langgraph_prebuilt", "xcagi_langgraph_sdk"])
def verifier(request):
    spec = importlib.util.spec_from_file_location(
        f"{request.param}_vendor_verifier", ROOT / f"packages/{request.param}/verify_vendor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recorded_runtime_patches_reconstruct_exact_upstream_bytes(verifier):
    assert verifier.verify_manifest()
    assert verifier.verify_local_patches(verifier.load_provenance())
    assert verifier.verify_license()


def test_changed_patch_or_upstream_identity_is_rejected(verifier):
    original = verifier.load_provenance()
    changed = copy.deepcopy(original)
    changed["local_patches"][0]["sha256"] = "0" * 64
    assert not verifier.verify_local_patches(changed)
    changed = copy.deepcopy(original)
    changed["upstream_manifest_sha256"] = "0" * 64
    assert not verifier.verify_local_patches(changed)
