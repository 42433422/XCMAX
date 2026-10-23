"""Bound interpreter probing without hiding repaired or broken environments."""

import shlex

import pytest

from modstore_server.maintenance_loop import review as impl


@pytest.fixture
def probe_environment(monkeypatch, tmp_path):
    candidates = [
        tmp_path / "override python",
        tmp_path / "deploy/.venv/bin/python",
        tmp_path / "runtime/MODstore_deploy/.venv/bin/python",
        tmp_path / "system python",
    ]
    for candidate in candidates:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("#!/bin/sh\nexit 1\n")
        candidate.chmod(0o700)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", raising=False)
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_TEST_PYTHON", str(candidates[0]))
    monkeypatch.setenv("MODSTORE_DEPLOY_ROOT", str(tmp_path / "deploy"))
    monkeypatch.setenv("MODSTORE_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(impl.sys, "executable", str(candidates[-1]))
    monkeypatch.setattr(impl, "_FOCUSED_TEST_PYTHON_CACHE", None, raising=False)
    clock, calls = [100.0], []
    monkeypatch.setattr(impl, "monotonic", lambda: clock[0], raising=False)
    original_probe = impl._python_supports_focused_tests

    def probe(candidate):
        calls.append(candidate)
        clock[0] += 10  # Include the worst-case probe duration in the expiry test.
        return original_probe(candidate)

    monkeypatch.setattr(impl, "_python_supports_focused_tests", probe)
    return candidates, clock, calls


@pytest.mark.parametrize("change", ["dependency_loss", "replacement", "removal", "repair"])
def test_probe_results_expire_including_fallback(probe_environment, change):
    candidates, clock, calls = probe_environment
    preferred = candidates[0]
    if change != "repair":
        preferred.write_text("#!/bin/sh\nexit 0\n")
    expected = candidates[-1] if change == "repair" else preferred
    assert shlex.split(impl._focused_test_command())[0] == str(expected)
    assert calls == (candidates if change == "repair" else [preferred])
    first_calls, expires_at = calls.copy(), clock[0] + 60
    if change == "removal":
        preferred.unlink()
    elif change == "replacement":
        replacement = preferred.with_suffix(".new")
        replacement.write_text("#!/bin/sh\nexit 1\n")
        replacement.chmod(0o700)
        replacement.replace(preferred)
    else:
        preferred.write_text(f"#!/bin/sh\nexit {0 if change == 'repair' else 1}\n")
    for clock[0] in (expires_at - 59, expires_at - 0.01):
        assert shlex.split(impl._focused_test_command())[0] == str(expected)
        assert calls == first_calls
    clock[0] = expires_at
    expected = preferred if change == "repair" else candidates[-1]
    assert shlex.split(impl._focused_test_command())[0] == str(expected)
    assert calls[len(first_calls) :] == ([preferred] if change == "repair" else candidates)


def test_configuration_changes_bypass_cached_fallback(probe_environment, monkeypatch):
    candidates, _, calls = probe_environment
    impl._focused_test_command()
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", "custom QA command")
    assert impl._focused_test_command() == "custom QA command"
    assert calls == candidates
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND")
    candidates[1].write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_TEST_PYTHON", str(candidates[1]))
    assert shlex.split(impl._focused_test_command())[0] == str(candidates[1])
    assert calls == candidates + [candidates[1]]
