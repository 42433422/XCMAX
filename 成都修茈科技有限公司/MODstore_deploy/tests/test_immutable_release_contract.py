from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


def test_immutable_release_is_exact_sha_atomic_and_rolls_back() -> None:
    script = (ROOT / "scripts/xcmax-immutable-release.sh").read_text(encoding="utf-8")

    assert "XCMAX_TARGET_SHA must be a full 40-character commit SHA" in script
    assert 'git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA"' in script
    assert "releases/${TARGET_SHA}" in script
    assert 'chmod 0555 "$FINAL_ROOT"' in script
    assert script.index('chmod 0555 "$FINAL_ROOT"') < script.index(
        'ln -s "$FINAL_ROOT" "${CURRENT_LINK}.next"'
    )
    assert 'mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"' in script
    assert "exact-SHA local health verification failed" in script
    assert 'sha256sum "$SOURCE_ARCHIVE"' in script
    assert 'payload.get("artifact_sha256") == expected_artifact' in script
    assert (
        'verify_health_identity "$PUBLIC_HEALTH_URL" "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA"'
        in script
    )
    assert "rollback" in script
    assert "reset --hard" not in script
    assert "/etc/xcmax" in script
    assert script.index('migrate_env_file "$ENV_FILE"') < script.index(
        "import fastapi, pytest, pytest_cov, uvicorn, modstore_server.app"
    )
    assert 'BUILD_JWT_SECRET="$(read_env_value "$ENV_FILE" MODSTORE_JWT_SECRET)"' in script
    assert "MODSTORE_ENV=production" in script
    assert 'MODSTORE_JWT_SECRET="$BUILD_JWT_SECRET"' in script
    assert 'MODSTORE_RUNTIME_DIR="$BUILD_ROOT/.runtime-build"' in script
    assert "MODSTORE_INSECURE_EMPTY_JWT" not in script
    assert ".[web,knowledge,evolution-metrics]" in script
    assert "import fastapi, pytest, pytest_cov, uvicorn, modstore_server.app" in script
    assert "Environment=MODSTORE_BUS=rabbitmq" not in script
    assert "npm ci --no-audit --legacy-peer-deps --ignore-scripts" in script
    assert "node scripts/install-native-bindings.mjs" in script
    assert script.index("--ignore-scripts") < script.index("npm run build")
    assert "resolve_java_home" in script
    assert "/usr/lib/jvm/java-17-*" in script
    assert 'PAYMENT_JAVA_BIN="${JAVA_HOME}/bin/java"' in script
    assert "ExecStart=${PAYMENT_JAVA_BIN} -jar" in script
    assert "verify_payment_identity" in script
    assert "/actuator/info" in script
    assert "MODSTORE_RELEASE_ARTIFACT_SHA256" in script
    assert 'RUNTIME_DIR="${MODSTORE_RUNTIME_DIR:-${RELEASE_BASE}/runtime}"' in script
    assert '[[ "$RUNTIME_DIR" == /* ]]' in script
    assert 'install -d -m 700 "$RUNTIME_DIR"' in script
    assert "MODSTORE_RUNTIME_DIR=%s" in script
    assert "MODSTORE_REPO_ROOT=%s" in script
    assert "XCMAX_MONOREPO_ROOT=%s" in script
    assert "JAVA_PAYMENT_SERVICE_URL=http://127.0.0.1:8080" in script
    assert '"$RUNTIME_DIR" "$CURRENT_LINK" "$CURRENT_LINK"' in script
    assert "verify_customer_value_reconciler" in script
    assert "customer value reconciler did not prove" in script
    payment_restart = script.index(
        "systemctl restart modstore-payment.service",
        script.index('ln -s "$FINAL_ROOT"'),
    )
    python_restart = script.index(
        "systemctl restart modstore.service modstore-scheduler.service",
        script.index('ln -s "$FINAL_ROOT"'),
    )
    assert payment_restart < python_restart
    assert script.index(
        "resolve_java_home", script.index("PAYMENT_SERVICE_PRESENT=0")
    ) < script.index("mvn -B -q -DskipTests package")

    source_ci = yaml.safe_load((ROOT / ".github/workflows/ci-backend-python.yml").read_text())
    published_ci = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/modstore-ci-backend-python.yml").read_text()
    )
    source_java_job = source_ci["jobs"]["java-payment-test"]
    published_java_job = published_ci["jobs"]["java-payment-test"]
    assert source_java_job["defaults"]["run"]["working-directory"] == "java_payment_service"
    assert published_java_job["defaults"]["run"]["working-directory"] == (
        "成都修茈科技有限公司/MODstore_deploy/java_payment_service"
    )
    assert any(step.get("run") == "mvn -B test package" for step in source_java_job["steps"])

    payment_config = yaml.safe_load(
        (ROOT / "java_payment_service/src/main/resources/application.yml").read_text()
    )
    assert payment_config["management"]["info"]["env"]["enabled"] is True
    assert payment_config["info"]["xcmax"]["git-sha"] == "${MODSTORE_GIT_SHA:}"
    assert payment_config["info"]["xcmax"]["artifact-sha256"] == (
        "${MODSTORE_RELEASE_ARTIFACT_SHA256:}"
    )


def test_production_workflow_deploys_only_successful_tested_main_sha() -> None:
    source = yaml.safe_load((ROOT / ".github/workflows/prod-deploy.yml").read_text())
    published = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/modstore-prod-deploy.yml").read_text()
    )

    for workflow in (source, published):
        trigger = workflow[True]
        assert trigger["workflow_run"]["workflows"] == ["CI - Backend Python"]
        deploy = workflow["jobs"]["deploy"]
        assert "workflow_run.conclusion == 'success'" in deploy["if"]
        rendered = str(deploy)
        assert "TARGET_SHA" in rendered
        assert "xcmax-immutable-release.sh" in rendered
        assert "modstore-deployment-correlation" in rendered
        assert "actions/upload-artifact@v4" in rendered
        assert "reset --hard" not in rendered


def test_production_receipt_finalizer_uses_completed_source_workflow_and_signed_callback() -> None:
    source = yaml.safe_load((ROOT / ".github/workflows/prod-deploy-receipt.yml").read_text())
    published = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/modstore-prod-deploy-receipt.yml").read_text()
    )

    for workflow in (source, published):
        trigger = workflow[True]
        assert trigger["workflow_run"]["workflows"] == ["Deploy MODstore Production"]
        receipt = workflow["jobs"]["receipt"]
        assert "workflow_run.conclusion == 'success'" in receipt["if"]
        rendered = str(receipt)
        assert "actions/download-artifact@v4" in rendered
        assert "MODSTORE_OPS_INGEST_TOKEN" in rendered
        assert "/api/ops/self-maintenance/deployment-receipt" in rendered
        assert "workflow_status" in rendered
        assert "completed" in rendered


def test_corp_site_deploy_uses_canonical_vhost_and_fails_closed_on_public_smoke() -> None:
    updater = (ROOT / "scripts/xcmax-site-auto-update.sh").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/corp-site-deploy.yml").read_text(encoding="utf-8")

    canonical_vhost = "/etc/nginx/conf.d/xiu-ci.com.conf"
    assert canonical_vhost in updater
    assert canonical_vhost in workflow
    assert "skip conflicting standalone corp vhost" in workflow
    for public_url in (
        "https://xiu-ci.com/",
        "https://xiu-ci.com/developer.html",
        "https://xiu-ci.com/market/download",
        "https://xiu-ci.com/market/",
    ):
        assert public_url in workflow
    assert "developer.html | head -8 | grep -i title || true" not in workflow
