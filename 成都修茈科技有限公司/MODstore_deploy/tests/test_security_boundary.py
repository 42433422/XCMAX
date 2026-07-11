from __future__ import annotations

import asyncio

import pytest

from modstore_server.security_boundary import (
    UnsafePath,
    opaque_ref,
    resolve_path_under_root,
    select_authorized_root,
)
from modstore_server.structured_json import parse_json_object, strip_json_fence


def test_resolve_path_under_root_accepts_nested_relative_path(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "result.txt"

    resolved = resolve_path_under_root(tmp_path, "nested/result.txt")

    assert resolved == target.resolve()


@pytest.mark.parametrize("requested", ["../outside.txt", "../../etc/passwd"])
def test_resolve_path_under_root_rejects_traversal(tmp_path, requested):
    with pytest.raises(UnsafePath):
        resolve_path_under_root(tmp_path, requested)


def test_resolve_path_under_root_rejects_absolute_path(tmp_path):
    with pytest.raises(UnsafePath):
        resolve_path_under_root(tmp_path, str(tmp_path / "result.txt"))


def test_resolve_path_under_root_rejects_sibling_prefix_collision(tmp_path):
    assigned = tmp_path / "assigned"
    sibling = tmp_path / "assigned-evil"
    assigned.mkdir()
    sibling.mkdir()

    with pytest.raises(UnsafePath):
        resolve_path_under_root(
            assigned,
            sibling / "secret.txt",
            require_relative=False,
        )


def test_resolve_path_under_root_accepts_filesystem_root(tmp_path):
    resolved = resolve_path_under_root(
        tmp_path.anchor,
        tmp_path,
        require_relative=False,
    )

    assert resolved == tmp_path.resolve()


def test_resolve_path_under_root_rejects_symlink_component(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePath):
        resolve_path_under_root(tmp_path, "link/secret.txt")


def test_resolve_path_under_root_rejects_symlink_component_with_in_root_target(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePath):
        resolve_path_under_root(tmp_path, "link/result.txt")


def test_resolve_path_under_root_rejects_resolved_symlink_escape(tmp_path):
    assigned = tmp_path / "assigned"
    outside = tmp_path / "outside"
    assigned.mkdir()
    outside.mkdir()
    link = assigned / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePath):
        resolve_path_under_root(
            assigned,
            "link/secret.txt",
            reject_symlinks=False,
        )


def test_select_authorized_root_returns_server_owned_path(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    assert select_authorized_root(str(allowed), [allowed]) == allowed.resolve()
    with pytest.raises(UnsafePath):
        select_authorized_root(str(tmp_path / "other"), [allowed])


def test_employee_runtime_rechecks_archive_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.employee_runtime as runtime

    assigned = tmp_path / "catalog"
    outside = tmp_path / "catalog-evil"
    assigned.mkdir()
    outside.mkdir()
    outside_archive = outside / "worker.xcemp"
    outside_archive.write_bytes(b"not-used")
    monkeypatch.setattr(runtime, "files_dir", lambda: assigned)
    monkeypatch.setattr(
        runtime,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside_archive,
    )

    issues = runtime.employee_pack_runtime_issues(
        {
            "stored_filename": "worker.xcemp",
            "manifest": {"employee_config_v2": {"actions": {"handlers": ["echo"]}}},
        }
    )

    assert issues == ["员工包 stored_filename 越过受控归档目录"]


def test_management_hash_rechecks_path_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.management_work_operations as operations

    assigned = tmp_path / "workspace"
    outside = tmp_path / "workspace-evil"
    assigned.mkdir()
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        operations,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside_file,
    )

    with pytest.raises(UnsafePath):
        operations._sha256_file(outside_file, workspace_root=assigned)


def test_management_compensation_rechecks_root_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.management_work_operations as operations

    assigned = tmp_path / "workspace"
    outside = tmp_path / "workspace-evil"
    assigned.mkdir()
    outside.mkdir()
    monkeypatch.setattr(
        operations,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside,
    )

    with pytest.raises(UnsafePath):
        operations.capture_file_compensation(outside / "secret.txt", workspace_root=assigned)


def test_agent_read_rechecks_path_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.mod_employee_agent_runner as runner

    assigned = tmp_path / "workspace"
    outside = tmp_path / "workspace-evil"
    assigned.mkdir()
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside_file,
    )

    result = asyncio.run(runner.tool_read_workspace_file(str(assigned), "secret.txt"))

    assert result["ok"] is False
    assert "越界" in result["error"]


def test_agent_ops_read_rechecks_path_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.mod_employee_agent_runner as runner

    assigned = tmp_path / "repo"
    outside = tmp_path / "repo-evil"
    assigned.mkdir()
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    def fake_resolve(root, requested, **_kwargs):
        return assigned.resolve() if requested == "." else outside_file.resolve()

    monkeypatch.setattr(runner, "resolve_path_under_root", fake_resolve)

    result = asyncio.run(
        runner.tool_read_workspace_file(
            str(assigned),
            "secret.txt",
            {"ops_readonly_repo_root": str(assigned)},
        )
    )

    assert result == {"ok": False, "error": "ops read failed: path is not authorized"}


def test_agent_write_rechecks_path_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.mod_employee_agent_runner as runner

    assigned = tmp_path / "workspace"
    outside = tmp_path / "workspace-evil"
    assigned.mkdir()
    outside.mkdir()
    outside_file = outside / "secret.txt"
    monkeypatch.setattr(
        runner,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside_file,
    )

    result = asyncio.run(
        runner.tool_write_workspace_file(str(assigned), "secret.txt", "must-not-write")
    )

    assert result["ok"] is False
    assert "越界" in result["error"]
    assert not outside_file.exists()


def test_management_read_scope_rechecks_path_returned_by_boundary(tmp_path, monkeypatch):
    import modstore_server.mod_employee_agent_runner as runner

    assigned = tmp_path / "workspace"
    outside = tmp_path / "workspace-evil"
    assigned.mkdir()
    outside.mkdir()
    monkeypatch.setattr(
        runner,
        "resolve_path_under_root",
        lambda *_args, **_kwargs: outside / "secret.txt",
    )

    error = runner._management_read_scope_error(
        str(assigned),
        "secret.txt",
        {"management_work_operation_context": {"task_id": "task-1"}},
        allow_scope_ancestor=False,
    )

    assert error == "路径越界"


def test_opaque_ref_does_not_expose_original_value():
    secret = "private-employee-token"

    first = opaque_ref(secret, namespace="test")
    second = opaque_ref(secret, namespace="test")

    assert first == second
    assert secret not in first
    assert len(first) == 16


def test_structured_json_parses_fenced_and_embedded_objects_linearly():
    fence = chr(96) * 3
    fenced = f'{fence}json\n{{"ok": false, "error": "failed"}}\n{fence}'
    embedded = 'prefix {"requires_human": true, "question": "approve?"} suffix'

    assert strip_json_fence(fenced).startswith('{"ok"')
    assert parse_json_object(fenced) == {"ok": False, "error": "failed"}
    assert parse_json_object(embedded, required_key="requires_human") == {
        "requires_human": True,
        "question": "approve?",
    }


def test_structured_json_handles_long_adversarial_fence_without_regex():
    fence = chr(96) * 3
    value = fence + ("\t" * 200_000)

    assert parse_json_object(value) == {}
