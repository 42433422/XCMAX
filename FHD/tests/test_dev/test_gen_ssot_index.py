"""gen_ssot_index 生成器单测：SSOT_INDEX.md 由 config/ssot.yaml 派生且与之同步。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # FHD
sys.path.insert(0, str(ROOT))


def test_doc_registry_loaded_from_yaml():
    """doc_registry 段被加载，含已知概念，共 13 条。"""
    from scripts.dev.gen_ssot_index import load_doc_registry

    registry = load_doc_registry()
    keys = {e["key"] for e in registry}
    assert {"coverage", "ci", "version", "ssot-framework", "coverage-metrics"} <= keys
    assert len(registry) == 13


def test_registered_paths_resolve_under_repo():
    """registered_paths 返回 {label: 绝对路径}，全部落在仓内。"""
    from scripts.dev.gen_ssot_index import REPO_ROOT, registered_paths

    paths = registered_paths()
    assert len(paths) == 13
    assert all(str(p).startswith(str(REPO_ROOT)) for p in paths.values())


def test_retired_paths_has_two_pointers():
    """retired 段含 2 条已退役指针。"""
    from scripts.dev.gen_ssot_index import retired_paths

    assert len(retired_paths()) == 2


def test_render_doc_has_banner_and_all_descriptions():
    """生成文档含「自动生成」横幅、「派生视图」标记，并列出每条 desc。"""
    from scripts.dev.gen_ssot_index import (
        GEN_LINE_PREFIX,
        load_doc_registry,
        render_doc,
    )

    doc = render_doc()
    assert GEN_LINE_PREFIX in doc
    assert "派生视图" in doc
    assert "config/ssot.yaml" in doc
    assert all(entry["desc"] in doc for entry in load_doc_registry())


def test_committed_index_is_in_sync():
    """仓库内 SSOT_INDEX.md 与 ssot.yaml 同步（改 ssot.yaml 后须重跑生成器并提交）。"""
    from scripts.dev.gen_ssot_index import is_fresh

    assert is_fresh(), "SSOT_INDEX.md 已过期，请运行 python scripts/dev/gen_ssot_index.py"
