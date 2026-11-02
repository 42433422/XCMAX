"""Public notice material is distinct from immutable backend/source identity."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "notice_material", ROOT / "scripts/package/notice_publication_material.py"
)
material = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(material)
SHA = "a" * 40


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    backend = tmp_path / "resources/backend"
    target = backend / "_internal/config/elt_notice_publication.json"
    target.parent.mkdir(parents=True)
    exe = backend / "xcagi-backend.exe"
    exe.write_bytes(b"immutable synthetic backend")
    info = tmp_path / "resources/build-info.json"
    info.write_text(
        json.dumps({"gitSha": SHA, "version": "1.0.0.7", "releaseId": f"xcagi-1.0.0.7-{SHA}"}),
        encoding="utf-8",
    )
    docs = material.publication_api().source_documents()
    record = {
        "notice_version": docs["service-agreement"]["version"],
        "recipient_disclosure_version": docs["privacy-policy"]["version"],
        "published_at": "2026-11-01T00:00:00Z",
    }
    source = tmp_path / "notice-publication.json"
    body = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    source.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    for key, value in {
        "XCAGI_NOTICE_PUBLICATION_FILE": str(source),
        "XCAGI_NOTICE_PUBLICATION_SHA256": digest,
        "XCAGI_NOTICE_PUBLICATION_ORIGIN": "https://www.xiu-ci.com",
        "XCAGI_NOTICE_PUBLICATION_BASE_PATH": "/admin",
    }.items():
        monkeypatch.setenv(key, value)
    return SimpleNamespace(
        backend=backend,
        target=target,
        exe=exe,
        info=info,
        source=source,
        body=body,
        digest=digest,
        record=record,
    )


def test_stage_preserves_record_time_backend_bytes_and_source_identity(bundle):
    before_exe = bundle.exe.read_bytes()
    before_info = json.loads(bundle.info.read_text())
    meta = material.stage_material(bundle.backend, bundle.info, SHA)
    assert meta == {
        "sha256": bundle.digest,
        "origin": "https://www.xiu-ci.com",
        "base_path": "/admin",
        "source_sha": SHA,
        "path": material.RECORD_PATH,
    }
    assert bundle.target.read_bytes() == bundle.body
    assert json.loads(bundle.target.read_text())["published_at"] == "2026-11-01T00:00:00Z"
    assert bundle.exe.read_bytes() == before_exe
    assert json.loads(bundle.info.read_text()) == {**before_info, "notice_publication": meta}
    assert material.verify_material(bundle.target, bundle.info, SHA, bundle.digest) == meta
    assert material.stage_material(bundle.backend, bundle.info, SHA) == meta


def test_material_verified_even_without_dispatch_environment(bundle, monkeypatch):
    meta = material.stage_material(bundle.backend, bundle.info, SHA)
    for key in (
        "XCAGI_NOTICE_PUBLICATION_FILE",
        "XCAGI_NOTICE_PUBLICATION_SHA256",
        "XCAGI_NOTICE_PUBLICATION_ORIGIN",
        "XCAGI_NOTICE_PUBLICATION_BASE_PATH",
    ):
        monkeypatch.delenv(key)
    assert material.verify_material(bundle.target, bundle.info, SHA) == meta


def test_omitted_material_keeps_existing_no_record_flow(bundle, monkeypatch):
    before = bundle.info.read_bytes()
    for key in (
        "XCAGI_NOTICE_PUBLICATION_FILE",
        "XCAGI_NOTICE_PUBLICATION_SHA256",
        "XCAGI_NOTICE_PUBLICATION_ORIGIN",
        "XCAGI_NOTICE_PUBLICATION_BASE_PATH",
    ):
        monkeypatch.delenv(key)
    assert material.stage_material(bundle.backend, bundle.info, SHA) is None
    assert bundle.info.read_bytes() == before
    assert not bundle.target.exists()


@pytest.mark.parametrize(
    "key",
    [
        "XCAGI_NOTICE_PUBLICATION_FILE",
        "XCAGI_NOTICE_PUBLICATION_SHA256",
        "XCAGI_NOTICE_PUBLICATION_ORIGIN",
        "XCAGI_NOTICE_PUBLICATION_BASE_PATH",
    ],
)
def test_partial_input_is_not_silently_ignored(bundle, monkeypatch, key):
    monkeypatch.delenv(key)
    with pytest.raises(ValueError, match="partial"):
        material.stage_material(bundle.backend, bundle.info, SHA)
    assert not bundle.target.exists()


@pytest.mark.parametrize(
    "mutation", ["hash", "extra", "version", "future", "source", "origin", "base_path"]
)
def test_invalid_material_does_not_change_staged_backend(bundle, monkeypatch, mutation):
    before = bundle.info.read_bytes()
    if mutation in {"extra", "version", "future"}:
        record = dict(bundle.record)
        if mutation == "extra":
            record["record_sha256"] = "not part of strict record"
        elif mutation == "version":
            record["notice_version"] = "old"
        else:
            record["published_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        bundle.source.write_text(json.dumps(record), encoding="utf-8")
        monkeypatch.setenv(
            "XCAGI_NOTICE_PUBLICATION_SHA256",
            hashlib.sha256(bundle.source.read_bytes()).hexdigest(),
        )
    elif mutation == "hash":
        monkeypatch.setenv("XCAGI_NOTICE_PUBLICATION_SHA256", "0" * 64)
    elif mutation == "origin":
        monkeypatch.setenv("XCAGI_NOTICE_PUBLICATION_ORIGIN", "https://xiu-ci.com/path")
    elif mutation == "base_path":
        monkeypatch.setenv("XCAGI_NOTICE_PUBLICATION_BASE_PATH", "/admin/../other")
    with pytest.raises(ValueError):
        material.stage_material(
            bundle.backend, bundle.info, "b" * 40 if mutation == "source" else SHA
        )
    assert bundle.info.read_bytes() == before
    assert not bundle.target.exists()


def test_different_existing_record_is_not_overwritten(bundle):
    bundle.target.write_bytes(b"existing frozen material")
    before = bundle.info.read_bytes()
    with pytest.raises(ValueError, match="replace"):
        material.stage_material(bundle.backend, bundle.info, SHA)
    assert bundle.target.read_bytes() == b"existing frozen material"
    assert bundle.info.read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "body",
        "missing",
        "path",
        "source_sha",
        "sha256",
        "origin",
        "base_path",
        "old_metadata",
        "metadata",
    ],
)
def test_packaged_record_or_provenance_mismatch_fails(bundle, mutation):
    material.stage_material(bundle.backend, bundle.info, SHA)
    info = json.loads(bundle.info.read_text())
    if mutation == "body":
        bundle.target.write_bytes(bundle.body + b" ")
    elif mutation == "missing":
        bundle.target.unlink()
    elif mutation == "metadata":
        del info["notice_publication"]
    elif mutation == "old_metadata":
        del info["notice_publication"]["base_path"]
    else:
        info["notice_publication"][mutation] = {
            "path": "../other.json",
            "source_sha": "b" * 40,
            "sha256": "0" * 64,
            "origin": "https://other.invalid",
            "base_path": "/other",
        }[mutation]
    bundle.info.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        material.verify_material(bundle.target, bundle.info, SHA, bundle.digest)


def test_windows_pipeline_consumes_and_checks_final_material():
    build = (ROOT / "scripts/package/build-installer.ps1").read_text(encoding="utf-8")
    installed = (ROOT / "scripts/package/verify-windows-installed-runtime.ps1").read_text(
        encoding="utf-8"
    )
    assert build.index("'notice_publication_material.py') stage") < build.index(
        "& npx @electronBuilderArgs"
    )
    assert build.index("'notice_publication_material.py') verify") > build.index(
        "& npx @electronBuilderArgs"
    )
    assert "win-unpacked\\resources" in build
    assert "'notice_publication_material.py') verify" in installed
    assert "if ($buildInfo.notice_publication)" in installed
    assert "--verify-notice-publication-sha256" in installed
    assert "$info.CreateNoWindow = $true" in installed
    assert "EnvironmentVariables.Remove('FHD_ELT_NOTICE_PUBLICATION')" in installed
    assert (
        installed.index("$noticeProbe.Start()")
        < installed.index("verify-probe")
        < installed.index("& $runtimeSmoke")
    )


def test_probe_environment_removes_only_runtime_override_in_child():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is unavailable")
    environment = {
        **os.environ,
        "NOTICE_PROBE_SCRIPT": str(ROOT / "scripts/package/verify-windows-installed-runtime.ps1"),
    }
    script = r"""
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:NOTICE_PROBE_SCRIPT,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'parse failure'}
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'New-NoticePublicationProbeStartInfo'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$env:FHD_ELT_NOTICE_PUBLICATION='parent-synthetic-record'
$env:NOTICE_PROBE_SENTINEL='keep'
$info=New-NoticePublicationProbeStartInfo -BackendExe 'synthetic.exe' -ProbeDir ([System.IO.Path]::GetTempPath()) -Digest ('a'*64)
if($info.EnvironmentVariables.ContainsKey('FHD_ELT_NOTICE_PUBLICATION')){throw 'child override retained'}
if($env:FHD_ELT_NOTICE_PUBLICATION -ne 'parent-synthetic-record'){throw 'parent environment changed'}
if($info.EnvironmentVariables['NOTICE_PROBE_SENTINEL'] -ne 'keep'){throw 'unrelated child environment changed'}
if(-not $info.CreateNoWindow -or $info.UseShellExecute){throw 'visible or shell process'}
Write-Output 'probe environment isolated'
"""
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "probe environment isolated" in result.stdout


@pytest.mark.parametrize("mutation", [None, "raw", "runtime", "missing", "contradiction"])
def test_installed_probe_evidence_matches_actual_loader_and_both_digests(
    bundle, monkeypatch, capsys, mutation
):
    from app.application import elt_login_authorization as auth
    from XCAGI import run_fastapi

    meta = material.stage_material(bundle.backend, bundle.info, SHA)
    monkeypatch.setattr(auth, "_NOTICE_PUBLICATION_FILE", bundle.target)
    monkeypatch.delenv(auth.NOTICE_PUBLICATION_ENV, raising=False)
    monkeypatch.setattr(run_fastapi, "_force_stdio_utf8", lambda _: None)
    run_fastapi.main(["--verify-notice-publication-sha256", bundle.digest])
    output = capsys.readouterr().out
    runtime_digest = auth.notice_publication()["record_sha256"]
    assert runtime_digest != bundle.digest
    if mutation == "raw":
        output = output.replace(bundle.digest, "0" * 64)
    elif mutation == "runtime":
        output = output.replace(runtime_digest, "0" * 64)
    elif mutation == "missing":
        output = ""
    elif mutation == "contradiction":
        output += "[notice-publication-probe] failed: synthetic\n"
    log = bundle.info.parent / "probe.stdout.log"
    log.write_text(output, encoding="utf-8")
    if mutation:
        with pytest.raises(ValueError, match="evidence mismatch"):
            material.verify_probe(bundle.info.parent, log, SHA, bundle.digest)
    else:
        assert material.verify_probe(bundle.info.parent, log, SHA, bundle.digest) == meta
    assert json.loads(bundle.target.read_text()) == bundle.record
