"""The sole LangGraph runtime copy remains reproducible after snapshot removal."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "langgraph_vendor_verifier", ROOT / "packages/xcagi_langgraph_core/verify_vendor.py"
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def test_recorded_runtime_patches_reconstruct_exact_upstream_bytes():
    assert verifier.verify_manifest()
    assert verifier.verify_local_patches(verifier.load_provenance())
    assert verifier.verify_license()


def test_changed_patch_or_upstream_identity_is_rejected():
    original = verifier.load_provenance()
    changed = copy.deepcopy(original)
    changed["local_patches"][0]["sha256"] = "0" * 64
    assert not verifier.verify_local_patches(changed)
    changed = copy.deepcopy(original)
    changed["upstream_manifest_sha256"] = "0" * 64
    assert not verifier.verify_local_patches(changed)
