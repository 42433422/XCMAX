from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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
    assert 'workflows: ["CI/CD Pipeline", "CI - Backend Python", "Source Governance"' in body
    assert '"cvm-autonomy-watcher"' in body
    assert '"FHD/CI/CD Pipeline"' not in body


def test_corporate_component_workflows_are_published_with_root_paths() -> None:
    root_frontend = publisher._render_corp(
        REPO_ROOT / "成都修茈科技有限公司" / ".github" / "workflows" / "ci-root-frontend.yml"
    )
    vibe = publisher._render_corp(
        REPO_ROOT / "成都修茈科技有限公司" / ".github" / "workflows" / "ci-vibe-coding.yml"
    )

    assert root_frontend is not None
    assert vibe is not None
    assert "working-directory: 成都修茈科技有限公司" in root_frontend[1]
    assert "cache-dependency-path: 成都修茈科技有限公司/package-lock.json" in root_frontend[1]
    assert "working-directory: 成都修茈科技有限公司/vibe-coding" in vibe[1]
    assert "- '成都修茈科技有限公司/vibe-coding/**'" in vibe[1]


@pytest.mark.parametrize("failed_workflow", ["", "fhd-security-full-scan.yml"])
def test_nightly_dispatch_supplies_required_inputs_and_propagates_failure(
    tmp_path: Path, failed_workflow: str
) -> None:
    source = REPO_ROOT / "FHD/.github/workflows/nightly-full.yml"
    rendered = publisher._render_fhd(source)
    assert rendered is not None
    workflow = yaml.load(rendered[1], Loader=yaml.BaseLoader)
    fanout = workflow["jobs"]["dispatch-nightly"]["steps"][-1]
    assert fanout["env"]["RELEASE_SHA"] == "${{ steps.target.outputs.sha }}"
    calls = tmp_path / "calls.jsonl"
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['workflow', 'run']:\n"
        "    sys.exit(1 if args[2] == os.environ['FAILED_WORKFLOW'] else 0)\n"
        "if args[:2] == ['run', 'list']:\n"
        "    print(json.dumps([{'databaseId': 7, 'createdAt': '2099-01-01T00:00:00Z', "
        "'headSha': os.environ['RELEASE_SHA'], 'event': 'workflow_dispatch'}]))\n"
        "elif args[:2] != ['run', 'watch']: sys.exit(3)\n"
    )
    gh.chmod(0o700)
    sha = "fd143dae58e26f01b9a9d86716abe7045fa1d507"
    result = subprocess.run(
        ["bash", "-c", fanout["run"]],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "CALLS": str(calls),
            "FAILED_WORKFLOW": failed_workflow,
            "REF": "main",
            "RELEASE_SHA": sha,
            "GH_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "example/test",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == (1 if failed_workflow else 0), result.stderr
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    dispatched = [command for command in commands if command[:2] == ["workflow", "run"]]
    assert len(dispatched) == 7
    assert len([c for c in commands if c[:2] == ["run", "watch"]]) == (0 if failed_workflow else 7)
    for command in dispatched:
        assert command[command.index("--ref") + 1] == "main"
        assert command[command.index("--repo") + 1] == "example/test"
        supplied = dict(
            command[index + 1].split("=", 1) for index, flag in enumerate(command) if flag == "-f"
        )
        target = yaml.load(
            (REPO_ROOT / ".github/workflows" / command[2]).read_text(), Loader=yaml.BaseLoader
        )
        declaration = target["on"]["workflow_dispatch"] or {}
        required = {
            key
            for key, spec in declaration.get("inputs", {}).items()
            if spec.get("required") == "true" and "default" not in spec
        }
        assert required <= supplied.keys()
        assert supplied == (
            {"release_sha": sha} if command[2] == "fhd-security-full-scan.yml" else {}
        )


def test_market_checks_initialized_child_without_mixing_parent_types() -> None:
    source = REPO_ROOT / "成都修茈科技有限公司/.github/workflows/ci-market.yml"
    rendered = publisher._render_corp(source)
    assert rendered is not None
    name, body = rendered
    assert name == "market-ci.yml"
    assert (REPO_ROOT / ".github/workflows" / name).read_text() == body
    workflow = yaml.load(body, Loader=yaml.BaseLoader)
    for event in ("push", "pull_request"):
        paths = workflow["on"][event]["paths"]
        assert ".gitmodules" in paths
        assert "成都修茈科技有限公司/.github/workflows/ci-market.yml" in paths
    job = workflow["jobs"]["market-ci"]
    steps = job["steps"]
    assert steps[0]["with"]["submodules"] == "true"
    assert any(step.get("run") == "npm run typecheck:ci" for step in steps)
    for name, command in (
        ("Install independent child dependencies", "npm ci --ignore-scripts"),
        ("Type check independent child", "./node_modules/.bin/tsc -b --force"),
    ):
        step = next(step for step in steps if step["name"] == name)
        assert step["run"] == command
        assert step["working-directory"] == (
            "成都修茈科技有限公司/MODstore_deploy/market/src/domain/客来来/desktop"
        )
