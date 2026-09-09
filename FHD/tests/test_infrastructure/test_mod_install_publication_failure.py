"""Signed installation fault injection preserves the last coherent code and receipt."""

from pathlib import Path

import pytest

from app.infrastructure.mods import install_receipts as receipts
from tests.test_infrastructure.test_mod_install_receipts import signed_mod as signed_mod


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("failure", ["archive", "receipt"])
def test_failed_install_publication_preserves_previous_version(
    signed_mod, monkeypatch, loaded, failure
):
    root, install = signed_mod
    install("1.0.0", "old")
    before = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    replace = receipts.os.replace

    def fail_once(source, destination):
        path = Path(destination)
        if (failure == "archive" and path.suffix == ".zip") or (
            failure == "receipt" and path.name == "receipt.json"
        ):
            raise OSError("synthetic publication failure")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_once)
        with pytest.raises(OSError, match="synthetic publication failure"):
            install("1.1.0", "new", loaded=loaded)
    assert (root / "fixture-mod/logic.py").read_text() == "old"
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) == before
    assert install("1.1.0", "new", loaded=loaded) is loaded
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["package_version"]
        == "1.1.0"
    )


def test_failed_restart_activation_restores_pending_package_and_old_code(signed_mod, monkeypatch):
    root, install = signed_mod
    install("1.0.0", "old")
    install("1.1.0", "new", loaded=True)
    before = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    monkeypatch.setattr(receipts, "PROCESS_ID", "different-process")
    replace = receipts.os.replace

    def fail_receipt(source, destination):
        if Path(destination).name == "receipt.json":
            raise OSError("synthetic receipt failure")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_receipt)
        with pytest.raises(OSError, match="synthetic receipt failure"):
            receipts.activate_pending_install("fixture-mod", mods_root=str(root))
    assert (root / "fixture-mod/logic.py").read_text() == "old"
    assert (Path(before["installed_root"]) / "logic.py").read_text() == "new"
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) == before
    assert receipts.activate_pending_install("fixture-mod", mods_root=str(root)) is True
    assert (root / "fixture-mod/logic.py").read_text() == "new"


def test_first_install_receipt_failure_leaves_no_untracked_active_code(signed_mod, monkeypatch):
    root, install = signed_mod
    replace = receipts.os.replace

    def fail_receipt(source, destination):
        if Path(destination).name == "receipt.json":
            raise OSError("synthetic first receipt failure")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_receipt)
        with pytest.raises(OSError, match="synthetic first receipt failure"):
            install("1.0.0", "new")
    assert not (root / "fixture-mod").exists()
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) is None
    assert install("1.0.0", "new") is False
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) is not None
