from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_mod_auto_publish_is_real_and_fail_closed() -> None:
    source = (ROOT / "FHD/.github/workflows/mod-auto-publish.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)
    prepare = workflow["jobs"]["prepare"]
    plan = next(step for step in prepare["steps"] if step.get("id") == "plan")
    assert "python FHD/scripts/dev/mod_publish_plan.py" in plan["run"]
    assert '--source-sha "$SOURCE_SHA" --repository "$GITHUB_REPOSITORY"' in plan["run"]
    assert '--mod-id "$REQUESTED_MOD_ID" --wait-seconds 1800' in plan["run"]

    publish_job = workflow["jobs"]["package-and-publish"]
    assert publish_job["needs"] == "prepare"
    assert publish_job["if"] == "needs.prepare.outputs.count != '0'"
    publish = next(
        step for step in publish_job["steps"] if "publish_modstore.py" in step.get("run", "")
    )
    assert publish["env"]["MODSTORE_AUTO_PUBLISH_TOKEN"] == (
        "${{ secrets.MODSTORE_AUTO_PUBLISH_TOKEN }}"
    )
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"' in publish["run"]
    assert '--sign --private-key "$key_path"' in publish["run"]
    # Review, public listing, download digest and internal duty filtering are
    # enforced by the real helper; the workflow must pass its provenance/roster.
    assert 'python FHD/scripts/dev/publish_modstore.py "$package"' in publish["run"]
    assert '--source-repository "$GITHUB_REPOSITORY" --source-sha "$SOURCE_SHA"' in publish["run"]
    assert '--workflow-run-id "$GITHUB_RUN_ID" --duty-roster FHD/config/duty_roster.json' in (
        publish["run"]
    )
    assert '--receipt "FHD/test_reports/modstore_publish/${MOD_ID}.receipt.json"' in publish["run"]
    for step in (plan, publish):
        assert "set -euo pipefail" in step["run"]
        assert not step.get("continue-on-error", False)
    assert "|| true" not in source


def test_production_deploy_uses_preprovisioned_auto_publish_secret() -> None:
    workflow = (
        ROOT / "成都修茈科技有限公司/MODstore_deploy/.github/workflows/prod-deploy.yml"
    ).read_text(encoding="utf-8")
    release = (
        ROOT / "成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-immutable-release.sh"
    ).read_text(encoding="utf-8")
    assert "AUTO_PUBLISH_TOKEN" not in workflow
    assert "envs: TARGET_SHA,STRICT_KEY" in workflow
    assert "upsert_protected_env_value" not in release
    assert (
        'BUILD_AUTO_PUBLISH_TOKEN="$(read_env_value "$ENV_FILE" MODSTORE_AUTO_PUBLISH_TOKEN)"'
        in release
    )
    assert "unset BUILD_AUTO_PUBLISH_TOKEN" in release
