"""Frozen-desktop contracts for the vendored LangGraph source gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.workflow import langgraph_assert


def _set_frozen(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)


@pytest.mark.parametrize(
    ("module_name", "relative_source"),
    [
        ("langgraph.graph.state", "langgraph/graph/state.py"),
        ("langgraph.checkpoint.sqlite", "langgraph/checkpoint/sqlite/__init__.py"),
    ],
)
def test_frozen_module_source_accepts_exact_meipass_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    relative_source: str,
) -> None:
    _set_frozen(monkeypatch, tmp_path)
    fake_module = SimpleNamespace(__file__=str(tmp_path / relative_source))
    monkeypatch.setattr(langgraph_assert.importlib, "import_module", lambda _name: fake_module)

    langgraph_assert._assert_module_source(module_name, "ignored-in-frozen-runtime")


@pytest.mark.parametrize(
    "source",
    [
        "../site-packages/langgraph/graph/state.py",
        "langgraph/graph/not_state.py",
    ],
)
def test_frozen_module_source_rejects_escape_or_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    _set_frozen(monkeypatch, tmp_path)
    fake_module = SimpleNamespace(__file__=str(tmp_path / source))
    monkeypatch.setattr(langgraph_assert.importlib, "import_module", lambda _name: fake_module)

    with pytest.raises(AssertionError):
        langgraph_assert._assert_module_source("langgraph.graph.state", "xcagi_langgraph_core")


def test_frozen_provenance_is_read_from_packaged_audit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_frozen(monkeypatch, tmp_path)
    package_dir = "xcagi_langgraph_core"
    provenance_dir = tmp_path / "vendored-provenance" / package_dir
    provenance_dir.mkdir(parents=True)
    (provenance_dir / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "upstream_tag": langgraph_assert.UPSTREAM_TAG,
                "upstream_commit_sha": langgraph_assert.UPSTREAM_COMMIT,
                "license": langgraph_assert.UPSTREAM_LICENSE,
            }
        ),
        encoding="utf-8",
    )

    langgraph_assert._assert_provenance(package_dir)


def test_frozen_runtime_without_meipass_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    with pytest.raises(AssertionError, match="_MEIPASS"):
        langgraph_assert._frozen_root()
