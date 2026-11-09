"""Shipment result writers must never follow untrusted parent/leaf links."""

import pytest

from app.application.shipment_excel_etl_security import (
    ShipmentEtlPathError,
    open_shipment_result_file,
)


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    root = tmp_path / "app-data"
    root.mkdir()
    monkeypatch.setenv("XCAGI_DATA_DIR", str(root))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    return root


def test_managed_result_creates_parents(app_data):
    destination = app_data / "etl" / "exports" / "run.xlsx"
    with open_shipment_result_file(destination) as stream:
        stream.write(b"result")
    assert destination.read_bytes() == b"result"


def test_failed_write_preserves_previous_result(app_data):
    destination = app_data / "etl" / "exports" / "run.xlsx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"previous")
    with pytest.raises(RuntimeError), open_shipment_result_file(destination) as stream:
        stream.write(b"partial")
        raise RuntimeError("interrupted")
    assert destination.read_bytes() == b"previous"
    assert list(destination.parent.glob(".etl-*.tmp")) == []


def test_untrusted_result_rejected(app_data, tmp_path):
    destination = tmp_path / "outside" / "run.xlsx"
    with pytest.raises(ShipmentEtlPathError), open_shipment_result_file(destination):
        pytest.fail("untrusted output opened")
    assert not destination.parent.exists()


@pytest.mark.parametrize("position", ["etl", "exports", "leaf"])
def test_result_links_rejected(app_data, tmp_path, position):
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "run.xlsx"
    protected.write_bytes(b"protected")
    target = app_data / "etl" / "exports" / "run.xlsx"
    link = (
        app_data / "etl"
        if position == "etl"
        else target.parent
        if position == "exports"
        else target
    )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(
        protected if position == "leaf" else outside, target_is_directory=position != "leaf"
    )
    with pytest.raises(ShipmentEtlPathError), open_shipment_result_file(target):
        pytest.fail("linked output opened")
    assert protected.read_bytes() == b"protected"


def test_parent_swap_cannot_redirect_write(app_data, tmp_path):
    destination = app_data / "etl" / "exports" / "run.xlsx"
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = app_data / "etl" / "pinned-exports"
    with open_shipment_result_file(destination) as stream:
        destination.parent.rename(moved)
        destination.parent.symlink_to(outside, target_is_directory=True)
        stream.write(b"safe")
    assert not (outside / "run.xlsx").exists()
    assert (moved / "run.xlsx").read_bytes() == b"safe"


def test_managed_traversal_rejected(app_data):
    destination = app_data / "etl" / "exports" / "unused" / ".." / "run.xlsx"
    with pytest.raises(ShipmentEtlPathError), open_shipment_result_file(destination):
        pytest.fail("traversal opened")
    assert not (app_data / "etl").exists()
