from __future__ import annotations

from pathlib import Path

from retort_engine.architecture_contracts import evaluate_architecture_contracts


def test_architecture_contracts_pass_when_forbidden_import_is_absent(tmp_path: Path) -> None:
    package = tmp_path / "retort_engine"
    package.mkdir()
    (package / "codebase_graph.py").write_text("import ast\nfrom pathlib import Path\n", encoding="utf-8")

    report = evaluate_architecture_contracts(tmp_path)

    assert report["status"] == "passed"
    assert report["summary"]["contract_count"] >= 1
    assert report["summary"]["violation_count"] == 0


def test_architecture_contracts_fail_on_forbidden_import(tmp_path: Path) -> None:
    package = tmp_path / "retort_engine"
    package.mkdir()
    (package / "codebase_graph.py").write_text("from retort_engine.core import RetortService\n", encoding="utf-8")

    report = evaluate_architecture_contracts(tmp_path)

    assert report["status"] == "failed"
    assert report["summary"]["violation_count"] == 1
    assert report["violations"][0]["contract"] == "codebase_graph_stays_foundational"
    assert report["violations"][0]["imported"] == "retort_engine.core.RetortService"


def test_architecture_contracts_accept_custom_contracts(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "ui.py").write_text("from app.domain import service\n", encoding="utf-8")

    report = evaluate_architecture_contracts(
        tmp_path,
        contracts=[
            {
                "name": "ui_cannot_import_domain",
                "type": "forbidden_import",
                "source": "app.ui",
                "forbidden": ["app.domain"],
            }
        ],
    )

    assert report["status"] == "failed"
    assert report["violations"][0]["source"] == "app.ui"
    assert report["violations"][0]["imported"] == "app.domain.service"
