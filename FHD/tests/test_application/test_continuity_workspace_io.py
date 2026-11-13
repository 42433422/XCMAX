"""Filesystem boundary regression tests; no provider or production side effects."""

import json
import os

import pytest

from app.application.employee_runtime.handoff_identity import load_identity_card
from app.application.employee_runtime.task_continuity import (
    TaskContinuityRuntime,
    ledger_path,
    load_employee_task_ledger,
    maybe_continue_employee_task,
)


def runtime(root):
    return TaskContinuityRuntime(ledger_path(root), workspace=root)


def test_atomic_ledger_roundtrip_preserves_business_state(tmp_path):
    r = runtime(tmp_path)
    r.state["tasks"]["t"] = {"business_data": {"amount": 31, "customer": "hello"}}
    with r._exclusive():
        r._write()
        r._read()
    assert load_employee_task_ledger(tmp_path) == r.state
    assert ledger_path(tmp_path).stat().st_mode & 0o777 == 0o600
    assert not list((tmp_path / ".xcmax").glob(".ledger-*.tmp"))


@pytest.mark.parametrize("leaf", ["employee_task_ledger.json", "employee_task_ledger.lock"])
def test_reject_leaf_symlink(tmp_path, leaf):
    d = tmp_path / ".xcmax"
    d.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("{}")
    (d / leaf).symlink_to(outside)
    with pytest.raises(OSError):
        with runtime(tmp_path)._exclusive():
            runtime(tmp_path)._read()
    assert outside.read_text() == "{}"


def test_reject_parent_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".xcmax").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        with runtime(tmp_path)._exclusive():
            pass
    assert not list(outside.iterdir())


def test_reject_workspace_ancestor_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        with runtime(alias)._exclusive():
            pass


def test_ledger_stays_on_locked_directory_after_rename(tmp_path):
    r = runtime(tmp_path)
    with r._exclusive():
        (tmp_path / ".xcmax").rename(tmp_path / "old")
        (tmp_path / ".xcmax").mkdir()
        r.state["tasks"]["t"] = {"result": "ok"}
        r._write()
        r._read()
    assert not ledger_path(tmp_path).exists()
    assert json.loads((tmp_path / "old/employee_task_ledger.json").read_text())["tasks"]["t"]


def test_reject_hardlinked_ledger(tmp_path):
    d = tmp_path / ".xcmax"
    d.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("{}")
    os.link(outside, ledger_path(tmp_path))
    with pytest.raises(ValueError):
        runtime(tmp_path)._read()


def test_reject_ledger_outside_explicit_workspace(tmp_path):
    with pytest.raises(ValueError):
        TaskContinuityRuntime(tmp_path.parent / "outside.json", workspace=tmp_path)


def test_body_cannot_supply_authority(tmp_path):
    result = maybe_continue_employee_task(
        "clerk", "", {"continuity_action": "start", "workspace_root": str(tmp_path)}
    )
    assert result["error_code"] == "continuity_workspace_missing"
    assert not (tmp_path / ".xcmax").exists()


@pytest.mark.parametrize("name", ["../outside", "/absolute", r"a\b", "a:b", ".."])
def test_tool_name_not_a_path(tmp_path, name):
    assert runtime(tmp_path)._execute_named_tool(name, {}, "t")["error_code"] == "tool_invalid"


def test_identity_roundtrip_and_link_rejection(tmp_path):
    d = tmp_path / "employees"
    d.mkdir()
    p = d / "clerk.json"
    p.write_text(json.dumps({"employee_id": "clerk", "tenant_id": "t1"}))
    assert load_identity_card(tmp_path, "clerk")[0]["tenant_id"] == "t1"
    outside = tmp_path / "outside.json"
    p.rename(outside)
    p.symlink_to(outside)
    assert load_identity_card(tmp_path, "clerk") == (None, "handoff_identity_unverified")


def test_identity_parent_link_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "clerk.json").write_text('{"employee_id":"clerk","tenant_id":"t1"}')
    (tmp_path / "employees").symlink_to(real, target_is_directory=True)
    assert load_identity_card(tmp_path, "clerk") == (None, "handoff_identity_unverified")


def test_shared_runtime_dispatch_serializes_ledger_descriptor(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    r = runtime(tmp_path)
    entered, release, second_started = Event(), Event(), Event()
    seen = []

    def metrics(actor, text, payload, **kwargs):
        fd = r._ledger_fd
        assert fd is not None
        os.fstat(fd)
        seen.append(text)
        if text == "first":
            entered.set()
            assert release.wait(3)
            assert r._ledger_fd == fd
            os.fstat(fd)
        r.state["side_effects"][text] = {"invocations": 1}
        r._write()
        return {"ok": True}

    r._metrics_op = metrics

    def second():
        second_started.set()
        return r.dispatch("clerk", "second", {"op": "metrics"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(r.dispatch, "clerk", "first", {"op": "metrics"})
        assert entered.wait(3)
        other = pool.submit(second)
        assert second_started.wait(3)
        try:
            assert not other.done()
            assert seen == ["first"]
        finally:
            release.set()
        assert first.result(timeout=3)["ok"]
        assert other.result(timeout=3)["ok"]
    assert seen == ["first", "second"]
    assert r._ledger_fd is None
    assert set(load_employee_task_ledger(tmp_path)["side_effects"]) == {"first", "second"}


@pytest.mark.parametrize("capability", ["O_DIRECTORY", "supports_dir_fd", "supports_fd"])
def test_identity_fails_closed_when_secure_handles_unavailable(tmp_path, monkeypatch, capability):
    d = tmp_path / "employees"
    d.mkdir()
    (d / "clerk.json").write_text('{"employee_id":"clerk","tenant_id":"t1"}')
    monkeypatch.delattr(os, capability)
    assert load_identity_card(tmp_path, "clerk") == (None, "handoff_identity_unverified")
    with pytest.raises(OSError, match="secure workspace handles are unavailable"):
        with runtime(tmp_path)._exclusive():
            pass


def test_restart_and_metrics_do_not_expose_or_mutate_other_tenants(tmp_path):
    r = runtime(tmp_path)
    first = r.dispatch("clerk", "owner one", {"op": "start", "tenant_id": "t1", "user_id": "u1"})
    second = r.dispatch("clerk", "owner two", {"op": "start", "tenant_id": "t2", "user_id": "u2"})
    own, foreign = first["task_id"], second["task_id"]
    r.state["side_effects"]["foreign-private-key"] = {"task_id": foreign, "invocations": 2}
    r.state["tool_calls"]["foreign-call"] = {
        "task_id": foreign,
        "step_id": "s",
        "status": "running",
        "submit_pid": 0,
        "tool_call_id": "foreign-call",
    }
    r._write()
    denied = r.dispatch(
        "clerk", "", {"op": "restart", "task_id": foreign, "tenant_id": "t1", "user_id": "u1"}
    )
    assert not denied["success"] and denied["error_code"] == "unauthorized"
    assert "owner two" not in json.dumps(denied)
    result = r.dispatch(
        "clerk", "", {"op": "restart", "task_id": own, "tenant_id": "t1", "user_id": "u1"}
    )
    assert result["success"]
    assert result["restart"]["inflight_recovered"] == []
    assert r.state["tool_calls"]["foreign-call"]["status"] == "running"
    metrics = r.dispatch("clerk", "", {"op": "metrics", "tenant_id": "t1", "user_id": "u1"})
    assert metrics["duplicate_side_effects"] == 0
    assert "foreign-private-key" not in json.dumps(metrics)
    assert r.duplicate_side_effects() == ["foreign-private-key"]  # Internal audit stays global.


def test_windows_identity_adapter_uses_pinned_native_read_contract(tmp_path, monkeypatch):
    from app.application import shipment_excel_elt_security as security
    from app.application.employee_runtime import workspace_io
    from app.application.shipment_elt import directory_listing

    folder = tmp_path / "employees"
    folder.mkdir()
    (folder / "clerk.json").write_text('{"employee_id":"clerk","tenant_id":"t1"}')
    calls = []

    def relative(parent_fd, name, **kwargs):
        calls.append((name, kwargs))
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if kwargs["directory"]:
            flags |= os.O_DIRECTORY
        return os.open(name, flags, dir_fd=parent_fd)

    monkeypatch.setattr(workspace_io, "_WINDOWS", True)
    monkeypatch.setattr(
        security,
        "_windows_open_anchor",
        lambda anchor, **kw: os.open(anchor, os.O_RDONLY | os.O_DIRECTORY),
    )
    monkeypatch.setattr(security, "_windows_open_relative", relative)
    monkeypatch.setattr(directory_listing, "list_directory_names", os.listdir)
    assert load_identity_card(tmp_path, "clerk")[0]["tenant_id"] == "t1"
    assert calls[-1] == ("clerk.json", {"directory": False, "create": False, "for_input": True})
    assert all(not args["create"] for _, args in calls)
    (folder / "clerk.json").unlink()
    (folder / "clerk.json").symlink_to(tmp_path / "outside")
    assert load_identity_card(tmp_path, "clerk") == (None, "handoff_identity_unverified")


def test_employee_entry_explicit_workspace_wins_over_nested_body(tmp_path):
    from app.application.employee_runtime.agent import EmployeeAgent

    foreign = tmp_path / "foreign"
    result = EmployeeAgent("clerk").run(
        "start",
        {
            "continuity_action": "start",
            "workspace_root": str(foreign),
            "tenant_id": "t1",
            "user_id": "u1",
        },
        workspace_root=str(tmp_path),
    )
    assert result["success"]
    assert ledger_path(tmp_path).is_file()
    assert not foreign.exists()
