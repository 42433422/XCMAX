"""Public URLs survive clean checkouts without committing publication copies."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
ASSETS = runpy.run_path(str(ROOT / "成都修茈科技有限公司/scripts/evidence_assets.py"))


@pytest.fixture
def repository(tmp_path):
    original = tmp_path / "FHD/docs/evidence/acceptance/original.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"accepted evidence bytes")
    entry = {
        "source": original.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "size": original.stat().st_size,
    }
    data = {
        "schema": "xcmax.evidence-materialization/v1",
        "retained_sources": {},
        "assets": {"old-public-url.png": entry, "second-public-url.png": entry},
    }
    manifest = tmp_path / ASSETS["MANIFEST"]
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(data))
    return tmp_path, original, manifest, data


def test_clean_checkout_rebuilds_exact_urls_and_bytes(repository):
    root, original, _, data = repository
    output = root / ASSETS["PUBLIC"]
    ASSETS["verified_sources"](root, data)
    assert not output.exists(), "checking source evidence must not create publication files"
    assert ASSETS["resolve_source"](root, ASSETS["PUBLIC"] + "/old-public-url.png") == original
    assert ASSETS["materialize"](root) == 2
    for name in data["assets"]:
        assert (output / name).read_bytes() == original.read_bytes()
        assert not (output / name).is_symlink()
    ASSETS["materialize"](root)
    assert sorted(p.name for p in output.iterdir()) == sorted(data["assets"])


def test_corrupt_original_stops_before_any_publication(repository):
    root, original, _, _ = repository
    original.write_bytes(b"different evidence bytes")
    with pytest.raises(ValueError, match="checksum mismatch"):
        ASSETS["materialize"](root)
    assert not (root / ASSETS["PUBLIC"]).exists()


@pytest.mark.parametrize(
    "source", ["../../outside.png", "FHD/docs/evidence/../../private.png", "config/secret.png"]
)
def test_unreviewed_source_paths_are_rejected(repository, source):
    root, _, manifest, data = repository
    data["assets"]["old-public-url.png"]["source"] = source
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unsafe|unregistered"):
        ASSETS["materialize"](root)


def test_materialization_cannot_follow_existing_alias_symlink(repository, tmp_path):
    root, _, _, _ = repository
    output = root / ASSETS["PUBLIC"]
    output.mkdir(parents=True)
    outside = tmp_path / "unrelated.txt"
    outside.write_bytes(b"leave this intact")
    (output / "old-public-url.png").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        ASSETS["materialize"](root)
    assert outside.read_bytes() == b"leave this intact"


def test_unique_original_is_retained_and_recovery_archive_roundtrips(repository):
    root, original, manifest, data = repository
    unique = root / ASSETS["PUBLIC"] / "unique-original.png"
    unique.parent.mkdir(parents=True)
    unique.write_bytes(b"unique original")
    data["retained_sources"][unique.name] = {
        "source": unique.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(unique.read_bytes()).hexdigest(),
        "size": unique.stat().st_size,
    }
    manifest.write_text(json.dumps(data))
    backup = root / "recovery.tar"
    ASSETS["archive"](root, backup)
    with tarfile.open(backup) as bundle:
        objects = [name for name in bundle.getnames() if name.startswith("objects/")]
        assert len(objects) == 2, "aliases must not duplicate content in the recovery archive"
    original.unlink()
    unique.unlink()
    ASSETS["restore"](root, backup)
    ASSETS["materialize"](root)
    assert unique.read_bytes() == b"unique original"
    assert original.read_bytes() == b"accepted evidence bytes"
    staging = root / "deployment"
    assert ASSETS["materialize"](root, staging) == 3
    assert (staging / unique.name).read_bytes() == unique.read_bytes()
    assert backup.stat().st_mode & 0o077 == 0


def test_bad_archive_does_not_restore_or_overwrite_any_original(repository):
    root, original, _, data = repository
    entry = next(iter(data["assets"].values()))
    archive = root / "corrupt.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("objects/" + entry["sha256"])
        member.size = entry["size"]
        bundle.addfile(member, io.BytesIO(b"x" * member.size))
    with pytest.raises(ValueError, match="archived evidence checksum mismatch"):
        ASSETS["restore"](root, archive)
    assert original.read_bytes() == b"accepted evidence bytes"


def test_historical_source_alias_keeps_record_bytes_and_reconstructs_original_layout(repository):
    root, original, manifest, data = repository
    alias = "FHD/docs/evidence/other-run/old-shot.png"
    data["source_aliases"] = {alias: next(iter(data["assets"].values()))}
    manifest.write_text(json.dumps(data))
    record = original.with_name("run.json")
    receipt = json.dumps(
        {"path": alias, "sha256": data["source_aliases"][alias]["sha256"]}
    ).encode()
    record.write_bytes(receipt)
    ASSETS["verified_sources"](root, ASSETS["load"](root))
    assert not (root / alias).exists()
    assert ASSETS["resolve_source"](root, alias) == original
    assert ASSETS["materialize"](root) == 3
    assert (root / alias).read_bytes() == original.read_bytes()
    assert record.read_bytes() == receipt


def test_source_alias_chains_are_rejected(repository):
    root, _, manifest, data = repository
    alias = "FHD/docs/evidence/other-run/old-shot.png"
    entry = dict(next(iter(data["assets"].values())))
    data["source_aliases"] = {alias: entry}
    data["assets"]["old-public-url.png"]["source"] = alias
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="canonical file"):
        ASSETS["materialize"](root)


def test_reconstruction_cannot_destroy_a_new_capture_at_a_historical_alias(repository):
    root, _, manifest, data = repository
    alias = "FHD/docs/evidence/other-run/old-shot.png"
    data["source_aliases"] = {alias: next(iter(data["assets"].values()))}
    manifest.write_text(json.dumps(data))
    fresh_capture = root / alias
    fresh_capture.parent.mkdir(parents=True)
    fresh_capture.write_bytes(b"new capture awaiting review")
    with pytest.raises(
        ValueError, match="refusing to overwrite different historical evidence alias"
    ):
        ASSETS["materialize_sources"](root)
    assert fresh_capture.read_bytes() == b"new capture awaiting review"


@pytest.mark.parametrize("reader", ["macos", "webadmin"])
def test_historical_registration_reads_alias_without_rewriting_evidence(
    repository, monkeypatch, reader
):
    root, original, manifest, data = repository
    alias = "FHD/docs/evidence/other-run/old-shot.png"
    data["source_aliases"] = {alias: next(iter(data["assets"].values()))}
    manifest.write_text(json.dumps(data))
    helper = root / ASSETS["SITE"] / "scripts/evidence_assets.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes((ROOT / ASSETS["SITE"] / "scripts/evidence_assets.py").read_bytes())
    if reader == "macos":
        monkeypatch.setitem(sys.modules, "acc_core", SimpleNamespace(REPO=root, OUT=root / "round"))
        module = runpy.run_path(
            str(ROOT / "FHD/docs/evidence/e2e/feature-acceptance-20260929/macos/acc_finalize.py")
        )
        digest_file = module["sha"]
    else:
        module = runpy.run_path(
            str(
                ROOT
                / "FHD/docs/evidence/e2e/feature-acceptance-webadmin-20260929/tools/register_evidence.py"
            )
        )
        digest_file = module["sha256_file"]
        monkeypatch.setitem(digest_file.__globals__, "REPO_ROOT", root)
    assert digest_file(root / alias) == hashlib.sha256(original.read_bytes()).hexdigest()
    assert not (root / alias).exists(), (
        "reading a historical alias must not recapture or rewrite evidence"
    )


def _git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)
        .decode()
        .strip()
    )


def test_guard_rejects_new_duplicate_media_but_allows_removing_legacy_copies(repository):
    root, original, _, _ = repository
    _git(root, "init", "-q")
    historical = original.with_name("historical-copy.png")
    historical.write_bytes(original.read_bytes())
    _git(root, "add", "FHD", ASSETS["MANIFEST"])
    _git(
        root,
        "-c",
        "user.name=Evidence test",
        "-c",
        "user.email=evidence@example.invalid",
        "commit",
        "-qm",
        "baseline",
    )
    base = _git(root, "rev-parse", "HEAD")
    ASSETS["guard"](root, base)
    new_copy = original.with_name("new-copy.png")
    new_copy.write_bytes(original.read_bytes())
    _git(root, "add", str(new_copy))
    with pytest.raises(ValueError, match="new duplicate media"):
        ASSETS["guard"](root, base)
    _git(root, "rm", "-f", str(new_copy), str(historical))
    ASSETS["guard"](root, base)


def test_guard_rejects_recommitting_generated_aliases(repository):
    root, _, _, _ = repository
    _git(root, "init", "-q")
    ASSETS["materialize"](root)
    _git(root, "add", ASSETS["PUBLIC"])
    with pytest.raises(ValueError, match="generated evidence is tracked"):
        ASSETS["guard"](root)


def test_guard_rejects_static_alias_even_when_it_differs_from_its_source(repository):
    root, original, _, _ = repository
    _git(root, "init", "-q")
    alias = "FHD/frontend/public/brand-copy.png"
    registry = root / "config/media-aliases.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps({"aliases": {alias: {"source": original.relative_to(root).as_posix()}}})
    )
    _git(root, "add", str(original))
    ASSETS["guard"](root)
    (root / alias).parent.mkdir(parents=True)
    (root / alias).write_bytes(b"unreviewed generated copy")
    _git(root, "add", alias)
    with pytest.raises(ValueError, match="generated media alias is tracked"):
        ASSETS["guard"](root)


@pytest.mark.parametrize("corrupt", [None, "evidence", "branding", "history"])
def test_actual_deployer_rebuilds_before_publishing_and_stops_on_corruption(repository, corrupt):
    root, original, _, _ = repository
    site = root / ASSETS["SITE"]
    helper = site / "scripts/evidence_assets.py"
    helper.parent.mkdir()
    helper.write_bytes((ROOT / ASSETS["SITE"] / "scripts/evidence_assets.py").read_bytes())
    media_builder = root / "scripts/dev/materialize_media_assets.mjs"
    media_builder.parent.mkdir(parents=True)
    media_builder.write_bytes((ROOT / "scripts/dev/materialize_media_assets.mjs").read_bytes())
    brand = root / "FHD/frontend/public/brand.jpg"
    brand.parent.mkdir(parents=True)
    brand.write_bytes(b"reviewed brand image")
    registry = root / "config/media-aliases.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "schema": "xcmax.media-aliases/v1",
                "aliases": {
                    f"{ASSETS['SITE']}/corp-butler/brand.jpg": {
                        "scope": "marketing",
                        "source": "FHD/frontend/public/brand.jpg",
                        "sha256": hashlib.sha256(brand.read_bytes()).hexdigest(),
                        "size": brand.stat().st_size,
                    }
                },
            }
        )
    )
    (site / "data").mkdir(exist_ok=True)
    for name in ("release-history.json", "release-presentation.json"):
        (site / "data" / name).write_text('{"derived":"approved-source"}')
    (site / "index.html").write_text("new page")
    live = root / "live"
    live.mkdir()
    (live / "index.html").write_text("previous page")
    (live / "download-release.json").write_text('{"verified":true}')
    (site / "download-release.json").write_text('{"candidate":"must-not-publish"}')
    (site / "corp-butler").mkdir(exist_ok=True)
    (site / "corp-butler/download-release.json").write_text('{"candidate":"stale-copy"}')
    (live / "corp-butler").mkdir()
    (live / "corp-butler/download-release.json").write_text('{"verified":true}')
    if corrupt == "evidence":
        original.write_bytes(b"changed after acceptance")
    elif corrupt == "branding":
        brand.write_bytes(b"unreviewed replacement")
    elif corrupt == "history":
        (site / "data/release-history.json").unlink()
    script = (
        ROOT / ASSETS["SITE"] / "MODstore_deploy/scripts/xcmax-site-auto-update.sh"
    ).read_text()
    function = re.search(r"^publish_site_static_to_live\(\) \{.*?^\}", script, re.M | re.S)
    assert function is not None
    env = {
        **os.environ,
        "XCMAX_ROOT": str(root),
        "SITE_SUBDIR": ASSETS["SITE"],
        "SITE_ROOT": str(live),
    }
    run = subprocess.run(
        [
            "bash",
            "-c",
            "set -eu\nlog() { :; }\n" + function.group() + "\npublish_site_static_to_live",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if corrupt:
        assert run.returncode != 0
        assert (live / "index.html").read_text() == "previous page"
        assert not (live / "capabilities").exists()
    else:
        assert run.returncode == 0, run.stderr
        assert (live / "index.html").read_text() == "new page"
        assert (live / "data/release-history.json").read_bytes() == (
            site / "data/release-history.json"
        ).read_bytes()
        assert (live / "data/release-presentation.json").read_bytes() == (
            site / "data/release-presentation.json"
        ).read_bytes()
        assert (
            live / "capabilities/assets/evidence/old-public-url.png"
        ).read_bytes() == original.read_bytes()
        assert (live / "corp-butler/brand.jpg").read_bytes() == brand.read_bytes()
        assert json.loads((live / "download-release.json").read_text()) == {"verified": True}
        assert json.loads((live / "corp-butler/download-release.json").read_text()) == {
            "verified": True
        }
