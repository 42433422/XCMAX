from pathlib import Path

import pytest

from scripts.dev import test_bloat_report as bloat


@pytest.fixture
def source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tests = tmp_path / "tests"
    app = tmp_path / "app"
    tests.mkdir()
    app.mkdir()
    (app / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(bloat, "TESTS_DIR", tests)
    monkeypatch.setattr(bloat, "APP_DIR", app)
    monkeypatch.setattr(bloat, "METRICS_FILE", tmp_path / "history.jsonl")
    return tests / "test_contract.py"


@pytest.mark.parametrize("seed", [False, True])
@pytest.mark.parametrize(
    "source,diagnostic",
    [
        ("assert True", "literal assert True"),
        ("assert response.status_code in (200, 500)", "both 2xx and 5xx"),
        ("assert response.status_code in [201, 503] and response.content", "both 2xx and 5xx"),
        ("assert status_code in {299, 599}", "both 2xx and 5xx"),
        ("assert response.status_code in (\n    204,\n    502,\n)", "both 2xx and 5xx"),
        ("def invalid(:", "cannot parse test source"),
    ],
)
def test_bad_source_cannot_seed_or_update_history(
    source_tree: Path, seed: bool, source: str, diagnostic: str, capsys: pytest.CaptureFixture
) -> None:
    source_tree.write_text(source + "\n", encoding="utf-8")
    assert bloat.cmd_check(seed=seed, record=True) == 1
    error = capsys.readouterr().err
    assert str(source_tree) in error
    assert diagnostic in error
    assert not bloat.METRICS_FILE.exists()


def test_error_contracts_and_fixture_strings_are_allowed(source_tree: Path) -> None:
    source_tree.write_text(
        'fixture = "assert True; assert response.status_code in (200, 500)"\n'
        "# assert True\n"
        "assert response.status_code == 500\n"
        "assert response.status_code in (400, 500, 503)\n"
        "assert response.status_code in (200, 204, 299)\n"
        "assert response.status_code in (199, 300, 499, 500)\n"
        "assert response.success is True\n",
        encoding="utf-8",
    )
    assert bloat.cmd_check() == 0
    history = bloat.METRICS_FILE.read_bytes()
    assert bloat.cmd_check() == 0
    assert bloat.METRICS_FILE.read_bytes() == history
