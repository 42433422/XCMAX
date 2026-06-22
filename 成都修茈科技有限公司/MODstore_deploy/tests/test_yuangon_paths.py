from __future__ import annotations

from pathlib import Path

from modstore_server.yuangon_paths import resolve_yuangon_repo_root


def _make_repo(root: Path) -> None:
    (root / "yuangon").mkdir(parents=True)
    (root / "MODstore_deploy" / "modstore_server").mkdir(parents=True)


def test_resolve_direct_yuangon_repo_root(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    assert resolve_yuangon_repo_root(tmp_path) == tmp_path.resolve()


def test_resolve_yuangon_from_deploy_root(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    assert resolve_yuangon_repo_root(tmp_path / "MODstore_deploy") == tmp_path.resolve()


def test_resolve_nested_xcmax_company_root(tmp_path: Path) -> None:
    company_root = tmp_path / "成都修茈科技有限公司"
    _make_repo(company_root)

    assert resolve_yuangon_repo_root(tmp_path) == company_root.resolve()


def test_resolve_unique_structural_child_when_company_name_changes(tmp_path: Path) -> None:
    company_root = tmp_path / "renamed-company"
    _make_repo(company_root)

    assert resolve_yuangon_repo_root(tmp_path) == company_root.resolve()


def test_resolve_prefers_runtime_snapshot_from_extra_roots(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    source_root = tmp_path / "source"
    _make_repo(runtime_root)
    _make_repo(source_root / "成都修茈科技有限公司")

    assert (
        resolve_yuangon_repo_root(
            source_root,
            extra_roots=[runtime_root],
        )
        == runtime_root.resolve()
    )


def test_resolve_keeps_original_root_when_yuangon_is_missing(tmp_path: Path) -> None:
    assert resolve_yuangon_repo_root(tmp_path) == tmp_path.resolve()
