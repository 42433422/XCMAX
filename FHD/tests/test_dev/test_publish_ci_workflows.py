from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "publish_ci_workflows_to_root.py"
SPEC = importlib.util.spec_from_file_location("publish_ci_workflows_to_root", SCRIPT)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def test_cvm_watcher_root_render_has_no_precheckout_working_directory() -> None:
    source = REPO_ROOT / "FHD" / ".github" / "workflows" / "cvm-autonomy-watcher.yml"

    rendered = publisher._render_fhd(source)

    assert rendered is not None
    _, body = rendered
    assert "defaults:\n  run:\n    working-directory: FHD" not in body
    assert "- name: Require CVM SSH secrets" in body


def test_security_full_scan_root_render_scans_monorepo_without_double_prefix() -> None:
    source = REPO_ROOT / "FHD" / ".github" / "workflows" / "security-full-scan.yml"

    rendered = publisher._render_fhd(source)

    assert rendered is not None
    _, body = rendered
    assert "defaults:\n  run:\n    working-directory: FHD" not in body
    assert "python FHD/scripts/security/normalize_security_report.py" in body
    assert "FHD/FHD/scripts/security" not in body
    assert 'docker run --rm -v "${PWD}:/repo"' in body


def test_modstore_deploy_root_render_has_no_precheckout_working_directory() -> None:
    source = (
        REPO_ROOT
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / ".github"
        / "workflows"
        / "prod-deploy.yml"
    )

    rendered = publisher._render_mod(source)

    assert rendered is not None
    _, body = rendered
    assert "working-directory: 成都修茈科技有限公司/MODstore_deploy" not in body
    assert "- name: Resolve exact tested SHA" in body


def test_ai_self_heal_workflow_run_names_are_not_path_prefixed() -> None:
    source = REPO_ROOT / "FHD" / ".github" / "workflows" / "ai-self-heal.yml"

    rendered = publisher._render_fhd(source)

    assert rendered is not None
    _, body = rendered
    # workflow display names must remain literal while the publisher rewrites paths.
    assert (
        'workflows: ["CI/CD Pipeline", "CI - Backend Python", "Source Governance"'
        in body
    )
    assert '"cvm-autonomy-watcher"' in body
    assert '"FHD/CI/CD Pipeline"' not in body


def test_corporate_component_workflows_are_published_with_root_paths() -> None:
    root_frontend = publisher._render_corp(
        REPO_ROOT
        / "成都修茈科技有限公司"
        / ".github"
        / "workflows"
        / "ci-root-frontend.yml"
    )
    vibe = publisher._render_corp(
        REPO_ROOT
        / "成都修茈科技有限公司"
        / ".github"
        / "workflows"
        / "ci-vibe-coding.yml"
    )

    assert root_frontend is not None
    assert vibe is not None
    assert "working-directory: 成都修茈科技有限公司" in root_frontend[1]
    assert (
        "cache-dependency-path: 成都修茈科技有限公司/package-lock.json"
        in root_frontend[1]
    )
    assert "working-directory: 成都修茈科技有限公司/vibe-coding" in vibe[1]
    assert "- '成都修茈科技有限公司/vibe-coding/**'" in vibe[1]
