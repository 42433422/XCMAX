"""Size is advisory; architectural, router, copy and source-boundary gates remain strict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from FHD.scripts import arch_fitness
from FHD.scripts.dev import count_big_files
from scripts.dev import source_governance
from scripts.dev.test_source_governance import baseline_state, current_state


@pytest.mark.parametrize("lines", [500, 501, 800, 801])
@pytest.mark.parametrize("stack", ["app", "modstore"])
def test_architecture_size_is_only_an_800_line_warning(
    tmp_path, monkeypatch, capsys, lines, stack
):
    fhd = tmp_path / "FHD"
    app = fhd / "app"
    modstore = tmp_path / "company/modstore_server"
    app.mkdir(parents=True)
    modstore.mkdir(parents=True)
    monkeypatch.setattr(arch_fitness, "REPO_ROOT", fhd)
    monkeypatch.setattr(arch_fitness, "APP_DIR", app)
    monkeypatch.setattr(arch_fitness, "MODSTORE_SERVER_DIR", modstore)
    monkeypatch.setattr(arch_fitness, "BASELINE_FILE", fhd / "baseline.txt")
    monkeypatch.setattr(arch_fitness, "VIOLATIONS", [])
    monkeypatch.setattr(arch_fitness, "WARNINGS", [], raising=False)
    target = app if stack == "app" else modstore
    (target / "large.py").write_text("# fixture\n" * lines)
    assert arch_fitness.main([]) == 0
    output = capsys.readouterr().out
    assert ("[giant-file]" in output) == (lines > 800)
    assert arch_fitness.main(["--update-baseline"]) == 0
    assert "[giant-file]" not in (fhd / "baseline.txt").read_text()
    (app / "domain").mkdir()
    (app / "domain/bad.py").write_text("from app.infrastructure import forbidden\n")
    assert arch_fitness.main([]) == 1
    assert "[domain->infrastructure]" in capsys.readouterr().out


def test_all_production_stacks_have_the_same_soft_cap():
    assert {
        cap for rule in source_governance.STACK_RULES for cap in rule.caps.values()
    } == {800}


@pytest.fixture
def fhd_size_fixture(tmp_path):
    original = (
        Path(__file__).resolve().parents[2] / "FHD" / count_big_files.BASELINE_REL
    )
    baseline = json.loads(original.read_text())
    baseline.update(
        big_files_over_800_lines=1,
        big_router_files_over_20_routes=0,
        file_line_limits={"app/large.py": 900},
        router_route_limits={},
        allowlist=[],
    )
    path = tmp_path / count_big_files.BASELINE_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(baseline))
    (tmp_path / "app").mkdir()
    (tmp_path / "app/large.py").write_text("# fixture\n" * 901)
    return tmp_path


def test_fhd_size_json_rejects_registered_growth(fhd_size_fixture, capsys):
    assert count_big_files.main(["--repo-root", str(fhd_size_fixture), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["warnings"] and report["errors"] and not report["ok"]
    assert "app/large.py" in report["errors"][0]


def test_fhd_baseline_requires_explicit_force_for_size_growth(fhd_size_fixture):
    args = ["--repo-root", str(fhd_size_fixture), "--update-baseline"]
    baseline_path = fhd_size_fixture / count_big_files.BASELINE_REL
    assert count_big_files.main(args) == 2
    assert json.loads(baseline_path.read_text())["file_line_limits"]["app/large.py"] == 900
    assert count_big_files.main([*args, "--force"]) == 0
    assert json.loads(baseline_path.read_text())["file_line_limits"]["app/large.py"] == 901
    (fhd_size_fixture / "app/routes.py").write_text(
        "\n".join(f"@router.get('/{i}')\ndef route_{i}(): pass" for i in range(21))
    )
    assert count_big_files.main(args) == 2
    assert json.loads(baseline_path.read_text())["router_route_limits"] == {}


@pytest.mark.parametrize("real_errors", [False, True])
def test_root_json_keeps_other_gates_blocking(
    tmp_path, monkeypatch, capsys, real_errors
):
    current = current_state(
        files=[
            {
                "file": "FHD/app/new.py",
                "stack": "fhd_backend",
                "lines": 801,
                "soft_cap": 800,
            }
        ]
    )
    if real_errors:
        current = current_state(
            files=current["oversized_files"],
            routers=[{"file": "FHD/app/routes.py", "routes": 31, "soft_cap": 20}],
            duplicate_lines=11,
            ignored=["ignored.py"],
            mirrors=["FHD/static/js/dead.js"],
        )
    monkeypatch.setattr(source_governance, "measure", lambda root: current)
    monkeypatch.setattr(
        source_governance, "load_baseline", lambda root: baseline_state()
    )
    assert source_governance.main(["--repo-root", str(tmp_path), "--json"]) == int(
        real_errors
    )
    report = json.loads(capsys.readouterr().out)
    assert len(report["warnings"]) == 1
    assert len(report["errors"]) == (4 if real_errors else 0)
    assert report["ok"] is not real_errors


def test_root_baseline_size_update_does_not_need_force(tmp_path, monkeypatch):
    current = current_state(
        files=[
            {
                "file": "FHD/app/legacy.py",
                "stack": "fhd_backend",
                "lines": 901,
                "soft_cap": 800,
            }
        ]
    )
    monkeypatch.setattr(source_governance, "measure", lambda root: current)
    monkeypatch.setattr(
        source_governance, "load_baseline", lambda root: baseline_state()
    )
    assert (
        source_governance.main(["--repo-root", str(tmp_path), "--update-baseline"]) == 0
    )
    saved = json.loads((tmp_path / source_governance.BASELINE_REL).read_text())
    assert saved["oversized_files"]["FHD/app/legacy.py"]["lines"] == 901


@pytest.mark.parametrize("checker", [count_big_files, source_governance])
def test_missing_and_malformed_baselines_do_not_pass(tmp_path, monkeypatch, checker):
    if checker is source_governance:
        monkeypatch.setattr(checker, "measure", lambda root: current_state())
    assert checker.main(["--repo-root", str(tmp_path)]) == 2
    path = tmp_path / checker.BASELINE_REL
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    with pytest.raises(json.JSONDecodeError):
        checker.main(["--repo-root", str(tmp_path)])


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        (prefix, suffix)
        for rule in source_governance.STACK_RULES
        for prefix in rule.prefixes
        for suffix in rule.caps
    ],
)
@pytest.mark.parametrize("lines", [500, 501, 800, 801])
def test_measured_boundary_for_every_production_stack(tmp_path, prefix, suffix, lines):
    relative = prefix + "boundary" + suffix
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# synthetic boundary\n" * lines)
    oversized, _ = source_governance._measure_sizes(tmp_path, [relative])
    assert len(oversized) == int(lines > 800)


@pytest.mark.parametrize(
    "kind", ["new_router", "router_growth", "duplicate", "ignored", "mirror"]
)
def test_baseline_update_never_absorbs_other_violations(tmp_path, monkeypatch, kind):
    baseline_path = tmp_path / source_governance.BASELINE_REL
    baseline_path.parent.mkdir(parents=True)
    before = json.dumps(baseline_state())
    baseline_path.write_text(before)
    current = current_state(
        files=[
            {
                "file": "FHD/app/large.py",
                "stack": "fhd_backend",
                "lines": 901,
                "soft_cap": 800,
            }
        ]
    )
    if kind in {"new_router", "router_growth"}:
        current["oversized_routers"] = [
            {
                "file": "FHD/app/new.py"
                if kind == "new_router"
                else "FHD/app/routes.py",
                "routes": 31,
                "soft_cap": 20,
            }
        ]
    elif kind == "duplicate":
        current["duplicate_metrics"]["redundant_lines"] += 1
    elif kind == "ignored":
        current["ignored_tracked_files"] = ["ignored.py"]
    else:
        current["forbidden_source_mirrors"] = ["FHD/static/js/old.js"]
    monkeypatch.setattr(source_governance, "measure", lambda root: current)
    assert (
        source_governance.main(["--repo-root", str(tmp_path), "--update-baseline"]) == 2
    )
    assert baseline_path.read_text() == before


@pytest.mark.parametrize("renamed", [False, True])
def test_fhd_router_identity_and_growth_stay_blocking(fhd_size_fixture, renamed):
    baseline_path = fhd_size_fixture / count_big_files.BASELINE_REL
    baseline = json.loads(baseline_path.read_text())
    baseline.update(
        big_router_files_over_20_routes=1, router_route_limits={"app/routes.py": 30}
    )
    before = json.dumps(baseline)
    baseline_path.write_text(before)
    name = "new_routes.py" if renamed else "routes.py"
    count = 21 if renamed else 31
    (fhd_size_fixture / "app" / name).write_text(
        "\n".join(f"@router.get('/{i}')\ndef route_{i}(): pass" for i in range(count))
    )
    assert count_big_files.main(["--repo-root", str(fhd_size_fixture)]) == 1
    assert (
        count_big_files.main(
            ["--repo-root", str(fhd_size_fixture), "--update-baseline"]
        )
        == 2
    )
    assert baseline_path.read_text() == before
