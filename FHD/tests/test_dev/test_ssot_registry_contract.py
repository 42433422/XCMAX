from __future__ import annotations

from pathlib import Path

import yaml

from scripts.dev.ssot_registry_contract import validate_registry_contract


def _write_registry(path: Path, domains: list[dict[str, object]]) -> None:
    path.write_text(yaml.safe_dump({"version": 1, "domains": domains}), encoding="utf-8")


def _write_index(path: Path, rows: list[str]) -> None:
    path.write_text(
        "\n".join(
            [
                "# SSOT",
                "## 领域 SSOT 登记表",
                "| 领域 | SSOT | 说明 | 执行注册名 |",
                "|------|------|------|------------|",
                *rows,
                "",
                "## other",
            ]
        ),
        encoding="utf-8",
    )


def test_registry_contract_accepts_exact_projection(tmp_path: Path) -> None:
    repo = tmp_path
    fhd = repo / "FHD"
    (fhd / "config").mkdir(parents=True)
    (fhd / "docs").mkdir()
    source = fhd / "config" / "source.json"
    source.write_text("{}", encoding="utf-8")
    registry = fhd / "config" / "ssot.yaml"
    index = fhd / "docs" / "SSOT_INDEX.md"
    _write_registry(registry, [{"name": "demo", "ssot": "FHD/config/source.json"}])
    _write_index(index, ["| demo | [source](../config/source.json) | demo | `demo` |"])

    assert validate_registry_contract(registry, index) == []


def test_registry_contract_rejects_unbound_machine_domain(tmp_path: Path) -> None:
    fhd = tmp_path / "FHD"
    (fhd / "config").mkdir(parents=True)
    (fhd / "docs").mkdir()
    registry = fhd / "config" / "ssot.yaml"
    index = fhd / "docs" / "SSOT_INDEX.md"
    _write_registry(registry, [{"name": "demo", "ssot": "FHD/config/source.json"}])
    _write_index(index, [])

    errors = validate_registry_contract(registry, index)

    assert any("demo has no SSOT_INDEX binding" in error for error in errors)


def test_registry_contract_rejects_path_drift(tmp_path: Path) -> None:
    fhd = tmp_path / "FHD"
    (fhd / "config").mkdir(parents=True)
    (fhd / "docs").mkdir()
    registry = fhd / "config" / "ssot.yaml"
    index = fhd / "docs" / "SSOT_INDEX.md"
    _write_registry(registry, [{"name": "demo", "ssot": "FHD/config/a.json"}])
    _write_index(index, ["| demo | [source](../config/b.json) | demo | `demo` |"])

    errors = validate_registry_contract(registry, index)

    assert any("registry path mismatch" in error for error in errors)
