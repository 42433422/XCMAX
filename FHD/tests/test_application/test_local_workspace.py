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
    with pytest.raises(ValueError, match="重复记录"):
        store.replace_from_mobile([mobile, mobile], workspace_id=old["workspace_id"])
    assert store.archives() == []
    assert store.snapshot() == old

    new = store.replace_from_mobile([mobile], workspace_id=old["workspace_id"])
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
