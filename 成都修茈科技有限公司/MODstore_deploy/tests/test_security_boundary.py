from __future__ import annotations

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
