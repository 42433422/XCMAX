"""Failed pending activation yields a failure receipt without stopping other Mods."""

import json
from pathlib import Path

import pytest

from app.infrastructure.mods import install_receipts as receipts
from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.registry import ModRegistry
from tests.test_infrastructure.test_mod_install_receipts import signed_mod as signed_mod


@pytest.mark.parametrize("mode", ["single", "all"])
@pytest.mark.parametrize("fault", ["tamper", "receipt"])
def test_activation_failure_preserves_old_code_and_does_not_abort_batch(
    signed_mod, monkeypatch, mode, fault
):
    root, install = signed_mod
    install("1.0.0", "old")
    install("1.1.0", "new", loaded=True)
    before = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    pending = Path(before["installed_root"])
    monkeypatch.setattr(receipts, "PROCESS_ID", "different-process")
    registry = ModRegistry()
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr("app.mod_sdk.product_skus.assert_mod_allowed_for_sku", lambda *_: None)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", lambda *_: True
    )
    manager = mod_manager.ModManager(mods_root=str(root))
    monkeypatch.setattr(manager, "all_mods_roots", lambda: [str(root)])
    independent = root / "independent"
    independent.mkdir()
    (independent / "manifest.json").write_text(
        json.dumps({"id": "independent", "name": "Independent", "version": "1.0"})
    )
    if fault == "tamper":
        (pending / "logic.py").write_text("tampered")
    else:
        replace = receipts.os.replace

        def fail_receipt(source, destination):
            if Path(destination).name == "receipt.json":
                raise OSError("synthetic activation failure")
            return replace(source, destination)

        monkeypatch.setattr(receipts.os, "replace", fail_receipt)
    if mode == "single":
        assert manager.load_mod("fixture-mod") is False
    else:
        assert manager.load_all_mods() == ["independent"]
    assert registry.get_mod_metadata("fixture-mod") is None
    assert (root / "fixture-mod/logic.py").read_text() == "old"
    assert pending.is_dir()
    assert any(row.get("stage") == "install_activation" for row in manager._recent_load_failures)
