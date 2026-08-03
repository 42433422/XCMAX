from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 release-gate runner.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
RELEASE_SCRIPT = ROOT / "scripts/xcmax-immutable-release.sh"
PYPROJECT = ROOT / "pyproject.toml"


def test_immutable_release_is_exact_sha_atomic_and_rolls_back() -> None:
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert "XCMAX_TARGET_SHA must be a full 40-character commit SHA" in script
    assert 'git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA"' in script
    assert 'FINAL_ROOT="${RELEASES_DIR}/${TARGET_SHA}"' in script
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
    assert "pandas>=2.0" in pyproject["project"]["optional-dependencies"]["evolution-metrics"]
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
    assert "MODSTORE_CAPABILITY_PROPOSAL_REPO=%s" in script
    assert 'GITHUB_REPOSITORY_SLUG="${XCMAX_GITHUB_REPOSITORY:-}"' in script
    assert "JAVA_PAYMENT_SERVICE_URL=http://127.0.0.1:8080" in script
    assert '"$RUNTIME_DIR" "$CURRENT_LINK" "$CURRENT_LINK"' in script
    assert "verify_customer_value_reconciler" in script
    assert "customer value reconciler did not prove" in script
    assert 'RELEASES_TO_KEEP="${XCMAX_RELEASES_TO_KEEP:-4}"' in script
    assert 'prune_releases "$CURRENT_ROOT_BEFORE_BUILD" "$RELEASES_DIR/$TARGET_SHA"' in script
    assert 'prune_releases "$FINAL_ROOT" "$PREVIOUS_ROOT"' in script
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


def test_release_retention_prunes_only_verified_sha_directories(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    release_base = tmp_path / "xcmax"
    releases = release_base / "releases"
    runtime = release_base / "runtime"
    env_dir = tmp_path / "env"
    public_state = tmp_path / "public"
    source_root.mkdir()
    (source_root / ".git").mkdir()
    releases.mkdir(parents=True)

    shas = [f"{number:040x}" for number in range(1, 7)]
    for position, sha in enumerate(shas, start=1):
        release = releases / sha
        release.mkdir()
        (release / ".xcmax-release.json").write_text(json.dumps({"git_sha": sha}), encoding="utf-8")
        os.utime(release, (position, position))

    malformed_sha = "f" * 40
    malformed = releases / malformed_sha
    malformed.mkdir()
    (malformed / ".xcmax-release.json").write_text(
        json.dumps({"git_sha": "0" * 40}), encoding="utf-8"
    )
    os.utime(malformed, (99, 99))
    unrelated = releases / "manual-backup"
    unrelated.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_flock = fake_bin / "flock"
    fake_flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_flock.chmod(0o755)
    current_link = release_base / "current"
    current_link.symlink_to(releases / shas[0])

    result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "XCMAX_ALLOW_CUSTOM_RELEASE_BASE": "1",
            "XCMAX_CURRENT_LINK": str(current_link),
            "XCMAX_PUBLIC_SITE_STATE_DIR": str(public_state),
            "XCMAX_RELEASE_BASE": str(release_base),
            "XCMAX_RELEASE_LOCK": str(tmp_path / "release.lock"),
            "XCMAX_RELEASE_PRUNE_ONLY": "1",
            "XCMAX_RELEASES_TO_KEEP": "3",
            "XCMAX_SOURCE_ROOT": str(source_root),
            "XCMAX_TARGET_SHA": shas[1],
            "MODSTORE_ENV_DIR": str(env_dir),
            "MODSTORE_RUNTIME_DIR": str(runtime),
        },
    )

    remaining = {item.name for item in releases.iterdir()}
    assert remaining.intersection(shas) == {shas[0], shas[1], shas[-1]}
    assert malformed_sha in remaining
    assert unrelated.name in remaining
    assert "release retention complete kept=3 removed=3 limit=3" in result.stdout
    assert "skipping unverified release directory" in result.stdout


def test_release_retention_rejects_unsafe_limit(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / ".git").mkdir()
    result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "XCMAX_ALLOW_CUSTOM_RELEASE_BASE": "1",
            "XCMAX_RELEASE_BASE": str(tmp_path / "xcmax"),
            "XCMAX_RELEASES_TO_KEEP": "1",
            "XCMAX_SOURCE_ROOT": str(source_root),
            "XCMAX_TARGET_SHA": "1" * 40,
        },
    )

    assert result.returncode != 0
    assert "XCMAX_RELEASES_TO_KEEP must be an integer greater than or equal to 2" in result.stderr


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
        assert "REPOSITORY_SLUG" in rendered
        assert "XCMAX_GITHUB_REPOSITORY" in rendered
        assert "xcmax-immutable-release.sh" in rendered
        assert "modstore-deployment-correlation" in rendered
        assert "actions/upload-artifact@v4" in rendered
        assert "reset --hard" not in rendered


def test_production_receipt_finalizer_uses_completed_source_workflow_and_signed_callback() -> None:
    source_path = ROOT / ".github/workflows/prod-deploy-receipt.yml"
    published_path = REPO_ROOT / ".github/workflows/modstore-prod-deploy-receipt.yml"
    source = yaml.safe_load(source_path.read_text())
    published = yaml.safe_load(published_path.read_text())

    for workflow in (source, published):
        trigger = workflow[True]
        assert trigger["workflow_run"]["workflows"] == ["Deploy MODstore Production"]
        assert trigger["workflow_dispatch"]["inputs"]["source_deploy_run_id"]["required"] is True
        assert "package_source_sha" in trigger["workflow_dispatch"]["inputs"]
        receipt = workflow["jobs"]["receipt"]
        assert "workflow_run.conclusion == 'success'" in receipt["if"]
        assert "github.event_name == 'workflow_dispatch'" in receipt["if"]
        rendered = str(receipt)
        assert workflow["permissions"]["pull-requests"] == "read"
        assert "actions/download-artifact@v4" in rendered
        assert "source deployment run id must be numeric" in rendered
        assert '.name == "Deploy MODstore Production"' in rendered
        assert ".head_sha == $merge_sha" in rendered
        assert "package source SHA is not an ancestor of deployed SHA" in rendered
        assert "steps.source.outputs.package_source_sha" in rendered
        assert "steps.source.outputs.merge_sha" in rendered
        assert "fetch-depth': 0" in rendered or "fetch-depth: 0" in rendered
        assert "/commits/${merge_sha}/pulls" in rendered
        assert "attested_branch_head_sha" in rendered
        assert "MODSTORE_OPS_INGEST_TOKEN" in rendered
        assert "/api/ops/self-maintenance/deployment-receipt" in rendered
        assert ".recorded == true or .idempotent == true" in rendered
        assert "/api/ops/self-maintenance/evolution-deployment-receipt" in rendered
        assert "evolution-packages.json" in rendered
        assert "catalog_data/files/" in rendered
        assert "stored_filename" in rendered
        assert "MODSTORE_AUTO_PUBLISH_TOKEN" in rendered
        assert "FHD/scripts/dev/publish_modstore.py" in rendered
        assert "modstore-evolution-publication-receipts" in rendered
        assert 'git show "${PACKAGE_SOURCE_SHA}:${archive}"' in rendered
        assert 'cmp --silent "$source_archive" "$archive"' in rendered
        assert "workflow_status" in rendered
        assert "completed" in rendered
    for workflow_path in (source_path, published_path):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        assert '"-z"' in workflow_text
        assert 'split(b"\\0")' in workflow_text
        assert "os.fsdecode" in workflow_text


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


def test_corp_site_deploy_publishes_and_verifies_world_will_ticker() -> None:
    updater = (ROOT / "scripts/xcmax-site-auto-update.sh").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/corp-site-deploy.yml").read_text(encoding="utf-8")
    homepage = (REPO_ROOT / "成都修茈科技有限公司/index.html").read_text(encoding="utf-8")
    visualization = (REPO_ROOT / "成都修茈科技有限公司/visualization.html").read_text(
        encoding="utf-8"
    )

    assert '"$git_site"/world-will-ticker.js' in updater
    assert '"$git_site"/world-will-ticker.css' in updater
    assert "'成都修茈科技有限公司/world-will-ticker.js'" in workflow
    assert "'成都修茈科技有限公司/world-will-ticker.css'" in workflow
    assert '"${GIT_SITE}/world-will-ticker.js"' in workflow
    assert '"${GIT_SITE}/world-will-ticker.css"' in workflow
    assert "https://xiu-ci.com/world-will-ticker.js" in workflow
    assert "https://xiu-ci.com/world-will-ticker.css" in workflow
    assert "grep -F -q '/api/public/action-board' /tmp/xc-world-will-ticker.js" in workflow
    for page in (homepage, visualization):
        assert 'href="/world-will-ticker.css?v=20260729a"' in page
        assert 'src="/world-will-ticker.js?v=20260729a"' in page
