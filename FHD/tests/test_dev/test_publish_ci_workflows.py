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
    # workflows 列表已扩展（Employee Smoke Gate / MODstore tests 等已加入），
    # 但前缀仍是 "CI/CD Pipeline", "Smoke Tests"——断言这两个前缀 + cvm-autonomy-watcher 存在即可。
    assert 'workflows: ["CI/CD Pipeline", "Smoke Tests"' in body
    assert '"cvm-autonomy-watcher"' in body
    assert '"FHD/CI/CD Pipeline"' not in body
