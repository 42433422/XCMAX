from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "release" / "verify_release_ready_chain.py"
)


def _mod():
    spec = importlib.util.spec_from_file_location("verify_release_ready_chain", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _five(sha: str, *, missing: str | None = None):
    modes = {m: {"passed": True} for m in ("Clean", "Upgrade", "Gui", "Recovery", "Rollback")}
    if missing:
        modes.pop(missing)
    return {
        "source_sha": sha,
        "modes": modes,
        "version": "1.0.0.7",
        "installer": "XCAGI-Enterprise-Setup-1.0.0.7-x64.exe",
        "installer_sha256": "c" * 64,
    }


def _receipt(sha):
    return {
        "ok": True,
        "git_sha": sha,
        **{
            k: v for k, v in _five(sha).items() if k in {"version", "installer", "installer_sha256"}
        },
    }


def test_current_download_release_keeps_release_ready_false():
    mod = _mod()
    payload = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "download_release.json").read_text()
    )
    result = mod.evaluate(payload, five_mode_evidence=None, prod_receipt=None)
    assert payload["release_ready"] is False
    assert result["passed"] is True
    assert "five_mode_evidence_missing" in result["blockers"]


def test_release_ready_true_without_chain_fails():
    mod = _mod()
    payload = {
        "release_ready": True,
        "download_version": "1.0.0.7",
        "artifacts": {"enterprise": {"win": "XCAGI-Enterprise-Setup-1.0.0.7-x64.exe"}},
    }
    result = mod.evaluate(payload, five_mode_evidence=None, prod_receipt=None)
    assert result["passed"] is False
    assert "release_ready_true_without_complete_chain" in result["blockers"]


def test_complete_chain_allows_release_ready():
    mod = _mod()
    sha = "a" * 40
    payload = {
        "release_ready": True,
        "download_version": "1.0.0.7",
        "artifacts": {"enterprise": {"win": "XCAGI-Enterprise-Setup-1.0.0.7-x64.exe"}},
    }
    result = mod.evaluate(
        payload,
        five_mode_evidence=_five(sha),
        prod_receipt=_receipt(sha),
    )
    assert result["blockers"] == []
    assert result["release_ready_allowed"] is True
    assert result["passed"] is True


@pytest.mark.parametrize("field", ["git_sha", "version", "installer", "installer_sha256"])
def test_release_ready_rejects_incomplete_installed_artifact_receipt(field):
    sha = "a" * 40
    receipt = _receipt(sha)
    receipt.pop(field)
    result = _mod().evaluate(
        {
            "release_ready": True,
            "download_version": "1.0.0.7",
            "artifacts": {"enterprise": {"win": _five(sha)["installer"]}},
        },
        five_mode_evidence=_five(sha),
        prod_receipt=receipt,
    )
    assert result["passed"] is False
    assert result["release_ready_allowed"] is False


@pytest.mark.parametrize(
    "field,bad",
    [
        ("source_sha", "z" * 40),
        ("installer_sha256", "z" * 64),
        ("installer", "other.exe"),
        ("version", "1.0.0.6"),
    ],
)
def test_five_mode_evidence_must_bind_the_same_original_installer(field, bad):
    sha = "a" * 40
    five = {**_five(sha), field: bad}
    result = _mod().evaluate(
        {
            "release_ready": True,
            "download_version": "1.0.0.7",
            "artifacts": {"enterprise": {"win": _five(sha)["installer"]}},
        },
        five_mode_evidence=five,
        prod_receipt=_receipt(sha),
    )
    assert result["release_ready_allowed"] is False


def test_incomplete_five_mode_blocks():
    mod = _mod()
    sha = "b" * 40
    payload = {
        "release_ready": True,
        "download_version": "1.0.0.7",
        "artifacts": {"enterprise": {"win": "setup.exe"}},
    }
    result = mod.evaluate(
        payload,
        five_mode_evidence=_five(sha, missing="Rollback"),
        prod_receipt={"ok": True, "git_sha": sha, "version": "1.0.0.7"},
    )
    assert "five_mode_failed_or_missing:Rollback" in result["blockers"]
    assert result["passed"] is False
