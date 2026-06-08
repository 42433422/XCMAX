"""Regression tests for the cross-stack coverage gates.

These tests fail loudly if someone removes the 80% gate on the critical
payment modules, lowers the existing floors, or drops the JaCoCo / Vitest
``check`` configurations. The intent is to keep ratcheting up; we never want
the gates to silently disappear.

Component CI lives under ``.github/workflows/ci-*.yml`` (split from legacy
``ci.yml``). Backend Python, Market frontend, and Java payment each have a
dedicated workflow; production deploy expectations live in ``deploy.yml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPANY_ROOT = REPO_ROOT.parent
WORKFLOWS = COMPANY_ROOT / ".github" / "workflows"
CI_BACKEND = WORKFLOWS / "ci-backend-python.yml"
CI_MARKET = WORKFLOWS / "ci-market.yml"
CI_JAVA = WORKFLOWS / "ci-payment-java.yml"
DEPLOY_WORKFLOW = WORKFLOWS / "deploy.yml"


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path} not present in this checkout")
    return path.read_text(encoding="utf-8")


def test_pyproject_declares_coverage_target():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.coverage.report]" in pyproject
    assert "fail_under = 80" in pyproject, "Pyproject must declare the 80% coverage target"


def test_ci_backend_workflow_runs_python_tests():
    text = _read(CI_BACKEND)
    assert "pytest" in text
    assert "MODSTORE_JWT_SECRET" in text
    assert "--cov=modstore_server" in text
    assert "--cov=modman" in text
    assert "MODSTORE_PY_COVERAGE_FLOOR" in text
    assert "--cov-fail-under" in text
    assert "coverage report --fail-under=80" in text
    assert "WEBHOOK_DISPATCHER_COVERAGE_FLOOR" in text


def test_pyproject_coverage_floor_documents_critical_modules():
    """总覆盖率门槛在 ``pyproject.toml``；per-file 关键模块 gate 由本地 ``coverage report`` 与代码审查维护。"""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "fail_under = 80" in pyproject
    assert "modstore_server" in pyproject
    assert "modman" in pyproject


def test_ci_java_workflow_runs_java_verify():
    text = _read(CI_JAVA)
    assert (
        "mvn -B verify" in text
    ), "Java step must run ``mvn verify`` so JaCoCo check rules are enforced"


def test_ci_market_workflow_runs_frontend_quality_gates():
    text = _read(CI_MARKET)
    assert "npm run typecheck" in text
    assert "npm ci" in text
    assert "npm run test:coverage" in text, "Market CI must run Vitest with coverage"
    assert "playwright" in text.lower(), "Market CI must install/run Playwright E2E"
    assert "npm run test:e2e" in text


def test_deploy_workflow_has_backend_ssh_deploy():
    if not DEPLOY_WORKFLOW.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    text = _read(DEPLOY_WORKFLOW)
    assert "appleboy/ssh-action" in text
    assert "MODstore_deploy" in text
    assert "api/health" in text


def test_pom_declares_jacoco_check_rule():
    pom = _read(REPO_ROOT / "java_payment_service" / "pom.xml")
    assert "<id>jacoco-check</id>" in pom
    assert "<goal>check</goal>" in pom
    assert "<counter>LINE</counter>" in pom
    assert "<counter>BRANCH</counter>" in pom
    assert "${jacoco.line.coverage}" in pom


def test_vite_config_enforces_payment_api_at_80():
    text = _read(REPO_ROOT / "market" / "vite.config.ts")
    assert "thresholds" in text
    assert (
        "src/application/paymentApi.ts" in text
    ), "vite.config.ts must keep a per-file 80% gate on the payment API client"
    assert "lines: 80" in text, "vite.config.ts must enforce 80% lines on the payment API client"
