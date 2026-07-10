from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FHD_ROOT = REPO_ROOT / "FHD"
FLUTTER_ROOT = FHD_ROOT / "mobile-flutter-poc"


def test_flutter_is_the_only_android_release_mainline() -> None:
    readme = (FLUTTER_ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (FHD_ROOT / ".github/workflows/release-android.yml").read_text(encoding="utf-8")

    assert "唯一生产交付主线" in readme
    assert "working-directory: mobile-flutter-poc" in workflow
    assert "flutter build apk --release" in workflow
    assert "flutter build appbundle --release" in workflow
    assert "flutter analyze" in workflow
    assert "flutter test --concurrency=4" in workflow
    assert "android_release_manifest.py" in workflow
    assert "android_release_manifest.json" in workflow
    assert "mobile-android" not in workflow


def test_release_pipeline_fails_closed_without_production_signing() -> None:
    workflow = (FHD_ROOT / ".github/workflows/release-android.yml").read_text(encoding="utf-8")
    gradle = (FLUTTER_ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    android_gitignore = (FLUTTER_ROOT / "android/.gitignore").read_text(encoding="utf-8")

    assert "Missing required production signing secret" in workflow
    assert "apksigner" in workflow
    assert "Android Debug" in workflow
    assert "debug-signed release " in gradle
    assert "artifacts are forbidden" in gradle
    assert 'else -> signingConfigs.getByName("debug")' not in gradle
    assert "keystore.properties" in android_gitignore


def test_published_root_workflow_keeps_flutter_working_directory() -> None:
    generated = (REPO_ROOT / ".github/workflows/fhd-release-android.yml").read_text(
        encoding="utf-8"
    )
    publisher = (REPO_ROOT / "scripts/dev/publish_ci_workflows_to_root.py").read_text(
        encoding="utf-8"
    )

    assert "working-directory: FHD/mobile-flutter-poc" in generated
    assert '"working-directory: mobile-flutter-poc"' in publisher
    assert '"working-directory: FHD/mobile-flutter-poc"' in publisher


def test_ota_uses_installed_package_version_and_live_legal_page() -> None:
    api = (FLUTTER_ROOT / "lib/src/api/mobile_api.dart").read_text(encoding="utf-8")
    models = (FLUTTER_ROOT / "lib/src/api/mobile_models.dart").read_text(encoding="utf-8")
    native = (
        FLUTTER_ROOT
        / "android/app/src/main/kotlin/com/xiuci/xcagi/xcagi_flutter_poc/MainActivity.kt"
    ).read_text(encoding="utf-8")

    assert "PackageInfo.fromPlatform()" in api
    assert "checkForUpdateForInstalledBuild" in api
    assert "appConfigForInstalledBuild" in api
    assert "https://xiu-ci.com/privacy.html" in models
    assert "https://xiu-ci.com/legal/privacy" not in models
    assert "https://xiu-ci.com/legal/terms" not in models
    assert "安装包缺少可信 SHA-256 校验值" in native
    assert 'setOf("xiu-ci.com", "www.xiu-ci.com")' in native
    assert 'startsWith("/download/enterprise/")' in native


def test_openapi_exposes_real_mobile_super_employee_cancellation() -> None:
    contract = json.loads((FHD_ROOT / "contracts/openapi.json").read_text(encoding="utf-8"))

    assert "/api/mobile/v1/admin/super-employee/tasks/{client_task_id}/cancel" in contract["paths"]
