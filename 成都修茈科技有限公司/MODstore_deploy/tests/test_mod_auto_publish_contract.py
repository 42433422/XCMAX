from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_mod_auto_publish_is_real_and_fail_closed() -> None:
    workflow = (ROOT / "FHD/.github/workflows/mod-auto-publish.yml").read_text(encoding="utf-8")
    assert "MODSTORE_AUTO_PUBLISH_TOKEN" in workflow
    assert "publish_modstore.py" in workflow
    assert "|| true" not in workflow
    assert "五维审核通过" in workflow
    assert "公开可见" in workflow
    assert "下载 SHA-256" in workflow
    assert "internal_only" in workflow
    assert "duty_roster.json" in workflow


def test_production_deploy_provisions_auto_publish_secret() -> None:
    workflow = (
        ROOT / "成都修茈科技有限公司/MODstore_deploy/.github/workflows/prod-deploy.yml"
    ).read_text(encoding="utf-8")
    release = (
        ROOT / "成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-immutable-release.sh"
    ).read_text(encoding="utf-8")
    assert "secrets.MODSTORE_AUTO_PUBLISH_TOKEN" in workflow
    assert 'MODSTORE_AUTO_PUBLISH_TOKEN="$AUTO_PUBLISH_TOKEN"' in workflow
    assert "upsert_protected_env_value" in release
    assert "MODSTORE_AUTO_PUBLISH_TOKEN" in release
