"""Regression tests for the cross-stack coverage gates.

These tests fail loudly if someone removes the 80% gate on the critical
payment modules, lowers the existing floors, or drops the JaCoCo / Vitest
``check`` configurations. The intent is to keep ratcheting up; we never want
the gates to silently disappear.

Component CI lives under ``.github/workflows/ci-*.yml`` (split from legacy
``ci.yml``). Backend Python, Market frontend, and Java payment each have a
dedicated workflow; production deploy expectations live in ``deploy.yml``.

CRITICAL — what GitHub *actually* runs: the backend Python workflow is a CI
SSOT. The authored file lives at
``成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml``
and is published to the XCMAX repo root as
``.github/workflows/modstore-ci-backend-python.yml`` by
``scripts/dev/publish_ci_workflows_to_root.py``. **GitHub Actions runs the root
copy**, not the component copy. A previous version of this test only checked the
``成都修茈科技有限公司/.github/workflows/ci-backend-python.yml`` orphan, which is
not what runs — giving a false "gate exists" signal while the running file had
no ``--cov-fail-under`` at all. We now assert the *running root* file and the
*published source* both carry the honest floor, and that all backend
``ci-backend-python.yml`` copies agree on it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent  # MODstore_deploy
COMPANY_ROOT = REPO_ROOT.parent  # 成都修茈科技有限公司
XCMAX_ROOT = COMPANY_ROOT.parent  # XCMAX repo root — where GitHub Actions runs
WORKFLOWS = COMPANY_ROOT / ".github" / "workflows"
CI_BACKEND = WORKFLOWS / "ci-backend-python.yml"
CI_MARKET = WORKFLOWS / "ci-market.yml"
CI_JAVA = WORKFLOWS / "ci-payment-java.yml"
DEPLOY_WORKFLOW = WORKFLOWS / "deploy.yml"

# The published source the publisher reads, and the root copy GitHub runs.
CI_BACKEND_SOURCE = REPO_ROOT / ".github" / "workflows" / "ci-backend-python.yml"
CI_BACKEND_RUNNING = XCMAX_ROOT / ".github" / "workflows" / "modstore-ci-backend-python.yml"

# Honest, conservative global coverage floor (ratchet). Not measured locally —
# ``xcagi_common`` requires Python>=3.10 — so we adopt pyproject's self-reported
# "全量 tree 约 40%+" as a floor that catches regressions and can only go up.
EXPECTED_COVERAGE_FLOOR = "40"


def _read_required(path: Path) -> str:
    """Read a file that MUST exist. Missing => hard failure, never a silent skip.

    Skipping on absence let the gate config disappear unnoticed; for the
    backend coverage gate we want a loud failure instead.
    """
    assert path.is_file(), f"required gate file missing: {path}"
    return path.read_text(encoding="utf-8")


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path} not present in this checkout")
    return path.read_text(encoding="utf-8")


def test_pyproject_declares_coverage_target():
    """pyproject 的 enforced floor 必须等于 CI 实际门禁(诚实值),不得是未兑现的 80。"""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.coverage.report]" in pyproject
    assert (
        f"fail_under = {EXPECTED_COVERAGE_FLOOR}" in pyproject
    ), f"Pyproject coverage floor must match the enforced CI floor ({EXPECTED_COVERAGE_FLOOR})"


def test_running_root_workflow_enforces_coverage_floor():
    """GitHub *实际运行* 的是发布到仓库根的那份;它必须真的带 --cov-fail-under。

    这是消除"覆盖率注水"的核心断言:此前测试只看组件目录的孤儿文件,
    给了"门禁存在"的假象,而真正运行的根文件根本没有 floor。
    """
    text = _read_required(CI_BACKEND_RUNNING)
    assert "pytest" in text
    assert "--cov=modstore_server" in text
    assert "--cov=modman" in text
    assert "--cov-fail-under" in text, "运行的根 workflow 必须带 --cov-fail-under(否则 0 门禁)"
    assert "MODSTORE_PY_COVERAGE_FLOOR" in text
    assert (
        f"MODSTORE_PY_COVERAGE_FLOOR: '{EXPECTED_COVERAGE_FLOOR}'" in text
    ), f"运行的根 workflow floor 必须是诚实值 {EXPECTED_COVERAGE_FLOOR}"


def test_published_source_workflow_enforces_coverage_floor():
    """发布源(publisher 读取的那份)也必须带同一诚实 floor,否则下次发布会把门禁冲掉。"""
    text = _read_required(CI_BACKEND_SOURCE)
    assert "--cov-fail-under" in text
    assert f"MODSTORE_PY_COVERAGE_FLOOR: '{EXPECTED_COVERAGE_FLOOR}'" in text


def test_ci_backend_workflow_runs_python_tests():
    text = _read_required(CI_BACKEND)
    assert "pytest" in text
    assert "MODSTORE_JWT_SECRET" in text
    assert "--cov=modstore_server" in text
    assert "--cov=modman" in text
    assert "MODSTORE_PY_COVERAGE_FLOOR" in text
    assert "--cov-fail-under" in text
    assert "coverage report --fail-under=80" in text
    assert "WEBHOOK_DISPATCHER_COVERAGE_FLOOR" in text


def test_all_backend_workflow_copies_agree_on_floor():
    """所有 ci-backend-python.yml 副本(组件孤儿 / 发布源 / 运行根)必须 floor 一致,避免再次漂移。"""
    needle = f"MODSTORE_PY_COVERAGE_FLOOR: '{EXPECTED_COVERAGE_FLOOR}'"
    for path in (CI_BACKEND, CI_BACKEND_SOURCE, CI_BACKEND_RUNNING):
        text = _read_required(path)
        assert needle in text, f"{path} 的 coverage floor 与诚实值 {EXPECTED_COVERAGE_FLOOR} 不一致"


def test_pyproject_coverage_floor_documents_critical_modules():
    """总覆盖率门槛在 ``pyproject.toml``；per-file 关键模块 gate 由本地 ``coverage report`` 与代码审查维护。"""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f"fail_under = {EXPECTED_COVERAGE_FLOOR}" in pyproject
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
    # Coverage thresholds live in vitest.config.ts (separate from vite build config)
    text = _read(REPO_ROOT / "market" / "vitest.config.ts")
    assert "thresholds" in text, "market/vitest.config.ts must define coverage thresholds"
    assert (
        "src/application/paymentApi.ts" in text
    ), "vitest.config.ts must keep a per-file 80% gate on the payment API client"
    assert "lines: 80" in text, "vitest.config.ts must enforce 80% lines on the payment API client"
