"""Tests for :class:`SkillPackager` — pure offline.

These tests exercise the staging layout and the produced ``.xcmod`` zip
without contacting MODstore. Any uploader / publisher tests live in
``test_publisher.py`` and use a stub HTTP transport.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from vibe_coding._internals import (
    CodeFunctionSignature,
    CodeSkill,
    CodeSkillVersion,
    CodeTestCase,
)
from vibe_coding.agent.marketplace import (
    PackagingError,
    SkillPackager,
    SkillPackageOptions,
)


@pytest.fixture
def sample_skill() -> CodeSkill:
    sig = CodeFunctionSignature(
        params=["text"], return_type="dict", required_params=["text"]
    )
    src = (
        '"""Reverse a string."""\n'
        "def reverse_text(text):\n"
        "    return {'reversed': text[::-1]}\n"
    )
    version = CodeSkillVersion(
        version=1,
        source_code=src,
        function_name="reverse_text",
        signature=sig,
        test_cases=[
            CodeTestCase(
                case_id="happy",
                input_data={"text": "hi"},
                expected_output={"reversed": "ih"},
            )
        ],
    )
    return CodeSkill(
        skill_id="reverse_string",
        name="Reverse String",
        domain="text",
        active_version=1,
        versions=[version],
    )


def test_package_minimal_skill_creates_xcmod(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(sample_skill)
    assert art.archive_path.is_file()
    assert art.archive_path.suffix == ".xcmod"
    assert art.pkg_id.startswith("vc-")
    assert art.sha256
    # The zip should at least contain the canonical files.
    with zipfile.ZipFile(art.archive_path) as zf:
        names = set(zf.namelist())
    expected_subset = {
        f"{art.pkg_id}/manifest.json",
        f"{art.pkg_id}/backend/__init__.py",
        f"{art.pkg_id}/backend/skill.py",
        f"{art.pkg_id}/backend/blueprints.py",
        f"{art.pkg_id}/backend/mod_init.py",
        f"{art.pkg_id}/frontend/routes.json",
        f"{art.pkg_id}/meta/skill.json",
        f"{art.pkg_id}/README.md",
    }
    missing = expected_subset - names
    assert not missing, f"missing entries: {missing}"


def test_manifest_passes_modstore_validation(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(
        sample_skill,
        options=SkillPackageOptions(
            pkg_id="reverse-string-vc", version="1.2.3", name="Reverse String"
        ),
    )
    with zipfile.ZipFile(art.archive_path) as zf:
        manifest_raw = zf.read(f"{art.pkg_id}/manifest.json").decode("utf-8")
    manifest = json.loads(manifest_raw)
    assert manifest["id"] == "reverse-string-vc"
    assert manifest["version"] == "1.2.3"
    assert manifest["name"] == "Reverse String"
    assert manifest["artifact"] == "mod"
    assert manifest["backend"]["entry"] == "blueprints"
    assert manifest["backend"]["init"] == "mod_init"
    assert manifest["frontend"]["routes"] == "frontend/routes.json"
    # The vibe-coding metadata block is preserved.
    assert manifest["vibe_coding"]["skill_id"] == "reverse_string"


def test_employee_pack_artifact_emits_employee_block(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(
        sample_skill,
        options=SkillPackageOptions(
            pkg_id="reverse-emp",
            version="1.0.0",
            artifact="employee_pack",
        ),
    )
    with zipfile.ZipFile(art.archive_path) as zf:
        manifest = json.loads(zf.read(f"{art.pkg_id}/manifest.json").decode("utf-8"))
    assert manifest["artifact"] == "employee_pack"
    assert manifest["employee"]["id"] == "reverse-emp"
    assert manifest["scope"] == "global"


def test_invalid_pkg_id_rejected(sample_skill: CodeSkill) -> None:
    pkg = SkillPackager()
    with pytest.raises(PackagingError):
        pkg.package_skill(
            sample_skill,
            options=SkillPackageOptions(pkg_id="UPPER_CASE_BAD"),
        )


def test_invalid_version_rejected(sample_skill: CodeSkill) -> None:
    pkg = SkillPackager()
    with pytest.raises(PackagingError):
        pkg.package_skill(
            sample_skill,
            options=SkillPackageOptions(pkg_id="ok-id", version="not a ver!"),
        )


def test_blueprint_includes_skill_endpoint(
    sample_skill: CodeSkill, tmp_path: Path
) -> None:
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(sample_skill)
    with zipfile.ZipFile(art.archive_path) as zf:
        bp_src = zf.read(f"{art.pkg_id}/backend/blueprints.py").decode("utf-8")
    assert "build_router" in bp_src
    assert "reverse_text" in bp_src
    assert "/reverse_string/run" in bp_src or "/reverse-string/run" in bp_src


def test_meta_tests_json_present(sample_skill: CodeSkill, tmp_path: Path) -> None:
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(sample_skill)
    with zipfile.ZipFile(art.archive_path) as zf:
        tests = json.loads(zf.read(f"{art.pkg_id}/meta/tests.json").decode("utf-8"))
    assert isinstance(tests, list)
    assert tests and tests[0]["case_id"] == "happy"


def test_workflow_bundles_siblings(sample_skill: CodeSkill, tmp_path: Path) -> None:
    sibling_sig = CodeFunctionSignature(
        params=["x"], return_type="dict", required_params=["x"]
    )
    sibling = CodeSkill(
        skill_id="echo",
        name="Echo",
        domain="util",
        active_version=1,
        versions=[
            CodeSkillVersion(
                version=1,
                source_code="def echo(x): return {'echo': x}\n",
                function_name="echo",
                signature=sibling_sig,
            )
        ],
    )
    pkg = SkillPackager(output_dir=tmp_path)
    art = pkg.package_skill(
        sample_skill,
        options=SkillPackageOptions(pkg_id="bundle-vc", version="1.0.0"),
        siblings=[sibling],
    )
    with zipfile.ZipFile(art.archive_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("bundle-vc/manifest.json").decode("utf-8"))
    assert "bundle-vc/backend/skill_echo.py" in names
    exports = {e["function_name"] for e in manifest["comms"]["exports"]}
    assert {"reverse_text", "echo"} <= exports
