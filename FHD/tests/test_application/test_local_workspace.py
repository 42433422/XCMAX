import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.local_workspace import LocalWorkspace, WorkspaceChanged


def _operation(op_id, record_id, *, kind="customer", base=None, deleted=False, **data):
    return {
        "op_id": op_id,
        "id": record_id,
        "kind": kind,
        "data": data,
        "deleted": deleted,
        "base_version": base,
    }


def test_persistence_duplicate_receipts_and_pull_cursor(tmp_path: Path):
    path = tmp_path / "device/workspace.sqlite3"
    store = LocalWorkspace(path)
    workspace_id = store.status()["workspace_id"]
    customer = _operation("customer-create", "customer-1", name="新客户")
    order = _operation(
        "order-create",
        "order-1",
        kind="order",
        status="draft",
        items=[{"product_id": "product-2", "quantity": 2}],
    )
    first = store.apply([customer, order], workspace_id=workspace_id)
    assert first["cursor"] == 2

    reopened = LocalWorkspace(path)
    retry = reopened.apply([order], workspace_id=workspace_id)
    assert retry["cursor"] == 2
    assert retry["results"] == first["results"][1:]

    delete = _operation("customer-delete", "customer-1", base="customer-create", deleted=True)
    assert reopened.apply([delete], workspace_id=workspace_id)["cursor"] == 3
    assert reopened.status() == {"workspace_id": workspace_id, "cursor": 3, "record_count": 1}

    page = reopened.pull(0, 2, workspace_id=workspace_id)
    assert page["has_more"] is True
    assert page["cursor"] == 2
    assert [change["record"]["version"] for change in page["changes"]] == [
        "customer-create",
        "order-create",
    ]
    last = reopened.pull(page["cursor"], 2, workspace_id=workspace_id)
    assert last["has_more"] is False
    assert last["cursor"] == 3
    assert last["changes"][0]["record"]["deleted"] is True
    assert reopened.pull(3, 2, workspace_id=workspace_id)["changes"] == []
    with pytest.raises(ValueError, match="游标"):
        reopened.pull(4, workspace_id=workspace_id)


def test_revision_conflict_and_operation_id_reuse_leave_data_intact(tmp_path: Path):
    store = LocalWorkspace(tmp_path / "workspace.sqlite3")
    original = _operation("create", "p", kind="product", name="原名")
    created = store.apply([original])["results"][0]["record"]
    changed = _operation("change", "p", kind="product", base="create", name="电脑已改")
    winner = store.apply([changed])["results"][0]["record"]
    assert winner["version"] == "change"

    stale = _operation("stale", "p", kind="product", base=created["version"], name="手机已改")
    conflict = {"op_id": "stale", "status": "conflict", "record": winner}
    assert store.apply([stale])["results"] == [conflict]

    missing_base = _operation("next", "missing", base="something", name="不存在")
    assert store.apply([missing_base])["results"] == [
        {"op_id": "next", "status": "conflict", "record": None}
    ]
    with pytest.raises(ValueError, match="重复"):
        store.apply([_operation("new", "c", name="应回滚"), {**original, "data": {"name": "重复"}}])

    assert store.snapshot()["records"] == [winner]
    assert store.status()["cursor"] == 2
    assert store.apply([stale])["results"] == [conflict]


def test_mobile_snapshot_archives_old_workspace_and_restores_in_new_epoch(tmp_path: Path):
    store = LocalWorkspace(tmp_path / "workspace.sqlite3")
    store.apply([_operation("desktop-create", "desktop", name="电脑客户")])
    old = store.snapshot()
    mobile = {
        "id": "mobile",
        "kind": "customer",
        "data": {"name": "手机客户"},
        "deleted": False,
        "version": "mobile-create",
    }
    options = {"workspace_id": old["workspace_id"], "max_snapshot_bytes": 65536}
    with pytest.raises(ValueError, match="重复记录"):
        store.bind_peer({}, records=[mobile, mobile], **options)
    assert store.archives() == []
    assert store.snapshot() == old

    new = store.bind_peer({}, records=[mobile], **options)
    assert new["workspace_id"] != old["workspace_id"]
    assert new["cursor"] == 0
    assert new["records"] == [mobile]
    assert store.archives()[0]["archive_id"] == new["archive_id"]
    assert store.archives()[0]["workspace_id"] == old["workspace_id"]
    with pytest.raises(WorkspaceChanged):
        store.apply([], workspace_id=old["workspace_id"])
    with pytest.raises(WorkspaceChanged):
        store.pull(0, workspace_id=old["workspace_id"])
    with pytest.raises(ValueError, match="重复"):
        store.apply([_operation("mobile-create", "mobile", base="mobile-create", name="冲突")])
    assert store.snapshot()["records"] == [mobile]

    with pytest.raises(ValueError, match="解除当前设备绑定"):
        store.restore_archive(new["archive_id"], workspace_id=new["workspace_id"])
    store.unbind_peer()
    restored = store.restore_archive(new["archive_id"], workspace_id=new["workspace_id"])
    assert restored["records"] == old["records"]
    assert restored["workspace_id"] not in {old["workspace_id"], new["workspace_id"]}
    assert len(store.archives()) == 2


def test_concurrent_updates_share_cas_and_separate_paths_stay_isolated(tmp_path: Path):
    path = tmp_path / "workspace.sqlite3"
    store = LocalWorkspace(path)
    store.apply([_operation("create", "shared", name="初始")])
    workspace_id = store.status()["workspace_id"]
    operations = [
        _operation(op_id, "shared", base="create", name=name)
        for op_id, name in [("desktop-edit", "电脑编辑"), ("phone-edit", "手机编辑")]
    ]

    def update(operation):
        return LocalWorkspace(path).apply([operation], workspace_id=workspace_id)["results"][0]

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(update, operations))
    assert {result["status"] for result in results} == {"applied", "conflict"}
    assert results[0]["record"] == results[1]["record"]
    assert store.status()["cursor"] == 2

    other = LocalWorkspace(tmp_path / "other.sqlite3")
    assert other.snapshot()["records"] == []
    assert other.status()["workspace_id"] != workspace_id
    with pytest.raises(WorkspaceChanged):
        other.apply([operations[0]], workspace_id=workspace_id)


def test_binding_write_failure_rolls_back_mobile_snapshot_and_archive(tmp_path: Path):
    path = tmp_path / "workspace.sqlite3"
    store = LocalWorkspace(path)
    store.apply([_operation("old-version", "old", name="Desktop")])
    old = store.snapshot()
    mobile = {
        "id": "mobile",
        "kind": "customer",
        "data": {"name": "Mobile"},
        "deleted": False,
        "version": "mobile-version",
    }
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TRIGGER fail_binding BEFORE INSERT ON peer_binding
               BEGIN SELECT RAISE(ABORT, 'failed to write binding'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="failed to write binding"):
        store.bind_peer(
            {"bind_request": "first"},
            workspace_id=old["workspace_id"],
            max_snapshot_bytes=65536,
            records=[mobile],
        )

    reopened = LocalWorkspace(path)
    assert reopened.snapshot() == old
    assert reopened.archives() == []
    assert reopened.peer_binding() == {}


def test_oversized_record_does_not_block_synchronizing_valid_records(tmp_path: Path):
    store = LocalWorkspace(tmp_path / "workspace.sqlite3")
    with pytest.raises(ValueError, match="64 KiB"):
        store.apply(
            [
                _operation("good", "good", name="Good"),
                _operation("large", "large", note="汉" * 22000),
            ]
        )
    assert store.pull(0)["changes"] == []
    store.apply([_operation("good", "good", name="Good")])
    assert store.pull(0)["cursor"] == 1


def test_archive_pages_keep_older_snapshots_available_for_restore(tmp_path: Path):
    store = LocalWorkspace(tmp_path / "workspace.sqlite3")
    store.apply([_operation("original", "old", name="保留的原始客户")])
    original = store.snapshot()["records"]
    archive_ids = []
    for _ in range(105):
        snapshot = store.bind_peer(
            {}, records=[], workspace_id=store.status()["workspace_id"], max_snapshot_bytes=65536
        )
        archive_ids.append(snapshot["archive_id"])
        store.unbind_peer()

    first = store.archive_page()
    last = store.archive_page(offset=100)
    assert first["total"] == last["total"] == 105
    assert [row["archive_id"] for row in first["archives"] + last["archives"]] == list(
        reversed(archive_ids)
    )
    assert len(first["archives"]) == 100 and len(last["archives"]) == 5
    assert all("records" not in row for row in first["archives"] + last["archives"])
    assert store.archive_page(offset=105) == {"archives": [], "total": 105}
    restored = store.restore_archive(archive_ids[0], workspace_id=store.status()["workspace_id"])
    assert restored["records"] == original
    assert store.archive_page()["total"] == 106


@pytest.mark.parametrize(
    "options", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 2**63}]
)
def test_archive_pages_reject_invalid_bounds(tmp_path: Path, options):
    with pytest.raises(ValueError, match="分页"):
        LocalWorkspace(tmp_path / "workspace.sqlite3").archive_page(**options)
