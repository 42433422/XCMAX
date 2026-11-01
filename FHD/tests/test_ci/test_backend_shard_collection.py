"""Early shards must preserve pytest discovery while importing only their files."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_ci.backend_shard_fixtures import IDENTITY

ROOT = Path(__file__).resolve().parents[2]


def run_shard(root: Path, index: int = 1, total: int = 1, *arguments: str):
    manifest = root / f"manifest-{index}.json"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("BACKEND_") and key not in {"PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    }
    env.update(
        IDENTITY,
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONPATH=str(ROOT),
        BACKEND_SHARD_INDEX=str(index),
        BACKEND_SHARD_TOTAL=str(total),
        BACKEND_SHARD_MANIFEST=str(manifest),
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "scripts.ci.backend_shards", "-q", *arguments],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    evidence = json.loads(manifest.read_text()) if manifest.is_file() else None
    return result, evidence


def assert_success(result):
    assert result.returncode == 0, result.stdout + result.stderr


def write_parameterized_module(path: Path, values: tuple[int, ...]):
    path.write_text(
        "from pathlib import Path\nimport pytest\n"
        f"with Path('imports.txt').open('a') as log: log.write({path.name!r} + '\\n')\n"
        "class TestCases:\n"
        f"    @pytest.mark.parametrize('value', {values!r})\n"
        "    def test_parameter(self, value): assert isinstance(value, int)\n"
    )


def test_only_assigned_files_import_and_new_parameters_execute(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    names = [f"test_{name}.py" for name in "abcd"]
    for name in names:
        write_parameterized_module(tmp_path / name, (0, 1))
    assignments, leaves = [], []
    for index in (1, 2):
        (tmp_path / "imports.txt").unlink(missing_ok=True)
        result, evidence = run_shard(tmp_path, index, 2)
        assert_success(result)
        assigned = evidence["assigned_files"]
        assert set((tmp_path / "imports.txt").read_text().splitlines()) == set(assigned)
        assert evidence["files"] == {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in names
        }
        assert evidence["collected"] == evidence["selected"]
        assert len(evidence["selected"]) == 2 * len(assigned)
        assert set(evidence["reports"]) == set(evidence["selected"])
        for name in assigned:
            assert evidence["collection_reports"][name][0]["outcome"] == "passed"
            assert name + "::TestCases" in evidence["collection_reports"]
        assignments.append(set(assigned))
        leaves.extend(evidence["selected"])
    assert assignments[0].isdisjoint(assignments[1])
    assert assignments[0] | assignments[1] == set(names)
    assert len(leaves) == len(set(leaves)) == 8

    changed = sorted(assignments[0])[0]
    write_parameterized_module(tmp_path / changed, (0, 1, 2))
    (tmp_path / "imports.txt").unlink()
    result, evidence = run_shard(tmp_path, 1, 2)
    assert_success(result)
    assert set(evidence["assigned_files"]) == assignments[0]
    assert changed + "::TestCases::test_parameter[2]" in evidence["selected"]
    assert len(evidence["reports"]) == 5
    assert set((tmp_path / "imports.txt").read_text().splitlines()) == assignments[0]


def test_empty_modules_and_import_skips_have_collection_receipts(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    for name in ("a", "b"):
        (tmp_path / f"test_{name}.py").write_text("def test_runs(): pass\n")
    (tmp_path / "test_c.py").write_text("EMPTY_MODULE = True\n")
    (tmp_path / "test_d.py").write_text(
        "import pytest\npytest.importorskip('xcagi_missing_shard_fixture_dependency')\n"
    )
    receipts, selected = {}, []
    for index in (1, 2):
        result, evidence = run_shard(tmp_path, index, 2)
        assert_success(result)
        for name in evidence["assigned_files"]:
            receipts[name] = evidence["collection_reports"][name]
        selected.extend(evidence["selected"])
    assert len(selected) == 2
    assert receipts["test_c.py"] == [{"outcome": "passed", "children": []}]
    assert receipts["test_d.py"] == [{"outcome": "skipped", "children": []}]


@pytest.mark.parametrize(
    "arguments",
    [
        ("test_a.py",),
        ("test_a.py::test_runs",),
        ("-k", "runs"),
        ("-m", "selected"),
        ("--ignore=test_b.py",),
        ("--ignore-glob=*b.py",),
        ("-o", "python_classes=NeverCollect"),
        ("-o", "python_functions=test_runs"),
        ("-c", "alternate.ini"),
        ("--noconftest",),
    ],
)
def test_partial_collection_options_fail_closed(tmp_path, arguments):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = selected\n")
    (tmp_path / "alternate.ini").write_text(
        "[pytest]\nmarkers = selected\npython_classes = NeverCollect\n"
    )
    for name in ("a", "b"):
        (tmp_path / f"test_{name}.py").write_text(
            "import pytest\n@pytest.mark.selected\ndef test_runs(): pass\ndef test_other(): pass\n"
            "class TestNested:\n    def test_nested(self): pass\n"
        )
    result, _ = run_shard(tmp_path, 1, 1, *arguments)
    assert result.returncode != 0, result.stdout + result.stderr


def test_conftest_cannot_silently_remove_an_assigned_file(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text("collect_ignore = ['test_b.py']\n")
    for name in ("a", "b"):
        (tmp_path / f"test_{name}.py").write_text("def test_runs(): pass\n")
    result, _ = run_shard(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr


def test_collection_hook_cannot_hide_a_nested_test(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items): items.pop(0)\n"
    )
    (tmp_path / "test_a.py").write_text(
        "class TestCases:\n    def test_first(self): pass\n    def test_second(self): pass\n"
    )
    result, _ = run_shard(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr


def test_shard_with_only_an_empty_module_is_rejected(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_a.py").write_text("def test_runs(): pass\n")
    (tmp_path / "test_b.py").write_text("EMPTY_MODULE = True\n")
    result, _ = run_shard(tmp_path, 2, 2)
    assert result.returncode != 0, result.stdout + result.stderr


def test_python_file_patterns_recursion_and_nested_fixtures_are_preserved(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = checks\npython_files = check_*.py\nnorecursedirs = ignored .*\n"
    )
    checks = tmp_path / "checks"
    (checks / "ignored").mkdir(parents=True)
    (checks / "conftest.py").write_text("import pytest\n@pytest.fixture\ndef answer(): return 42\n")
    for name in ("a", "b"):
        (checks / f"check_{name}.py").write_text("def test_fixture(answer): assert answer == 42\n")
    for path in (checks / "test_nonmatching.py", checks / "ignored/check_hidden.py"):
        path.write_text("raise RuntimeError('must not be imported')\n")
    assigned = []
    for index in (1, 2):
        result, evidence = run_shard(tmp_path, index, 2)
        assert_success(result)
        assert set(evidence["files"]) == {"checks/check_a.py", "checks/check_b.py"}
        assert len(evidence["selected"]) == 1
        assigned.extend(evidence["assigned_files"])
    assert sorted(assigned) == ["checks/check_a.py", "checks/check_b.py"]


@pytest.mark.parametrize("config_name", ["pytest.toml", ".pytest.toml", "pyproject.toml"])
def test_native_toml_cannot_override_the_verified_collection_configuration(tmp_path, config_name):
    if config_name != "pyproject.toml":
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
    section = "tool.pytest" if config_name == "pyproject.toml" else "pytest"
    (tmp_path / config_name).write_text(f"[{section}]\npython_classes = ['NeverCollect']\n")
    (tmp_path / "test_a.py").write_text(
        "def test_function(): pass\nclass TestNested:\n    def test_hidden(self): pass\n"
    )
    result, _ = run_shard(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Native pytest TOML configuration is unsupported" in result.stdout + result.stderr


@pytest.mark.parametrize("setting", ["python_files", "norecursedirs"])
@pytest.mark.parametrize("separator", ["/", "\\"])
def test_path_globs_are_rejected_instead_of_using_different_pytest_semantics(
    tmp_path, setting, separator
):
    # Native TOML arrays preserve the backslash for the supported ini-options table.
    pattern = (
        f"nested{separator}test_*.py" if setting == "python_files" else f"nested{separator}skip"
    )
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.pytest.ini_options]\n{setting} = [{json.dumps(pattern)}]\n"
    )
    (tmp_path / "test_a.py").write_text("def test_runs(): pass\n")
    result, _ = run_shard(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "basename" in result.stdout + result.stderr


@pytest.mark.parametrize("package", [False, True], ids=["namespace-directory", "package-directory"])
def test_module_directory_name_collisions_cannot_silently_hide_tests(tmp_path, package):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --import-mode=importlib\n")
    (tmp_path / "test_group.py").write_text("def test_top_level(): pass\n")
    directory = tmp_path / "test_group"
    directory.mkdir()
    (directory / "test_nested.py").write_text("def test_nested(): pass\n")
    if package:
        (directory / "__init__.py").write_text("")
    result, _ = run_shard(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
