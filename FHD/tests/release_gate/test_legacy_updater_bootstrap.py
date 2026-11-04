import base64
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import runpy
import subprocess
import tarfile
from pathlib import Path

import pytest

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts/deploy/fhd-push-release.sh"
SHA = "a" * 40
NAMES = [
    "fhd-auto-update.sh",
    "fhd-apply-release.sh",
    "fhd-apply-release-compose.sh",
    "fhd-load-release-image.sh",
    "lib/deploy_emit.sh",
    "lib/autonomy_gate.sh",
    "lib/verify_release_identity.sh",
    "lib/dora_event.sh",
    "lib/version.sh",
    "lib/verify_admin_console.py",
    "lib/mod_tree_guard.py",
    "lib/verify_release_archive.py",
    "lib/service_quiescence.sh",
    "lib/apply_recovery.sh",
    "prune_release_cache.py",
]


def test_controller_inventory_is_included_in_the_release_archive():
    pack = (FHD / "scripts/deploy/fhd-pack-release.sh").read_text()
    for name in NAMES:
        assert f'"$SCRIPT_DIR/{name}"' in pack or f'"$FHD_ROOT/scripts/deploy/{name}"' in pack, name


@pytest.fixture
def setup(tmp_path):
    text = SCRIPT.read_text()
    source = text.split("<<'PY_BOOTSTRAP'\n", 1)[1].split("\nPY_BOOTSTRAP", 1)[0]
    module_path = tmp_path / "release_controller_bootstrap.py"
    module_path.write_text(source)
    spec = importlib.util.spec_from_file_location("release_controller_bootstrap", module_path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.PROC_ROOT = tmp_path / "proc"
    m.PROC_ROOT.mkdir()
    m.LOCK_PATH = tmp_path / "updater.lock"
    root = tmp_path / "runtime"
    m.LEGACY_DEPLOY_ROOT = root
    deploy = root / "scripts/deploy"
    deploy.mkdir(parents=True)
    immutable = tmp_path / "immutable"
    immutable.mkdir()
    channel = tmp_path / "stable/server"
    channel.mkdir(parents=True)
    old = {}
    new = {}
    verifier_path = FHD / "scripts/deploy/lib/verify_release_archive.py"
    verifier_source = verifier_path.read_bytes()
    required = runpy.run_path(str(verifier_path))["REQUIRED_RUNTIME_MEMBERS"]
    for name in NAMES:
        p = deploy / name
        p.parent.mkdir(parents=True, exist_ok=True)
        data = b"# original controller\n"
        p.write_bytes(data)
        p.chmod(0o700)
        old[name] = data
        new[name] = b"# reviewed helper\n" if name.endswith(".py") else b"#!/bin/bash\nexit 77\n"
    new["lib/verify_release_archive.py"] = verifier_source
    for name in [".build-identity.json", ".env", "XCAGI/mods/customer/data.db"]:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"untouched-user-state")
    (channel / "fhd-manifest.json").write_bytes(b"old-pointer")
    (channel / "fhd-manifest.json.frozen").write_bytes(b"human-freeze")
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in new.items()}
    args = [
        str(immutable),
        str(channel),
        "release.tar.gz",
        "0",
        "stable",
        str(root),
        SHA,
        "",
        base64.b64encode(json.dumps(expected).encode()).decode(),
        "0",
        base64.b64encode(verifier_source).decode(),
    ]

    def pack(identity=SHA, changed=None, link=None):
        with tarfile.open(immutable / args[2], "w:gz") as tar:
            payload = {
                **dict.fromkeys(required, b"fixture runtime file\n"),
                ".build-identity.json": json.dumps({"git_sha": identity}).encode(),
                **{"scripts/deploy/" + k: v for k, v in new.items()},
                "app/main.py": b"user runtime",
            }
            if changed:
                payload["scripts/deploy/" + changed] = b"# different source\n"
            for name, data in payload.items():
                info = tarfile.TarInfo("./" + name)
                info.size = len(data)
                if link and name == "scripts/deploy/" + link:
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/outside"
                    info.size = 0
                    tar.addfile(info)
                else:
                    tar.addfile(info, io.BytesIO(data))
        args[7] = hashlib.sha256((immutable / args[2]).read_bytes()).hexdigest()
        manifest = {
            "artifact": args[2],
            "git_sha": SHA,
            "sha256": args[7],
            "archive_verifier_sha256": hashlib.sha256(verifier_source).hexdigest(),
        }
        (immutable / "fhd-manifest.json").write_text(json.dumps(manifest))

    pack()
    return m, args, root, deploy, channel, old, new, pack


def unchanged(setup):
    _, _, root, deploy, channel, old, _, _ = setup
    assert (channel / "fhd-manifest.json").read_bytes() == b"old-pointer"
    assert all((deploy / name).read_bytes() == data for name, data in old.items())
    assert all(
        (root / name).read_bytes() == b"untouched-user-state"
        for name in [".build-identity.json", ".env", "XCAGI/mods/customer/data.db"]
    )


def test_upgrades_controllers_under_same_lock_before_manifest_and_never_runs_them(
    setup, monkeypatch
):
    m, args, root, deploy, channel, old, new, _ = setup
    original = m.atomic_bytes

    def inspect(path, data, mode):
        with m.LOCK_PATH.open("a+") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path == channel / "fhd-manifest.json":
            assert all((deploy / name).read_bytes() == data_ for name, data_ in new.items())
        original(path, data, mode)

    monkeypatch.setattr(m, "atomic_bytes", inspect)
    m.bootstrap_promote(args)
    assert json.loads((channel / "fhd-manifest.json").read_text())["git_sha"] == SHA
    assert (channel / "fhd-manifest.json.frozen").read_bytes() == b"human-freeze"
    backups = list(
        (root.parent / ("." + root.name + "-controller-backups") / SHA).glob("controller-*")
    )
    assert len(backups) == 1
    inventory = json.loads((backups[0] / "backup.json").read_text())
    for name, data in old.items():
        assert (backups[0] / name).read_bytes() == data
        assert inventory[name]["sha256"] == hashlib.sha256(data).hexdigest()
        assert inventory[name]["mode"] == 0o700
    for name in [".build-identity.json", ".env", "XCAGI/mods/customer/data.db"]:
        assert (root / name).read_bytes() == b"untouched-user-state"


@pytest.mark.parametrize("bad", ["hash", "identity", "controller", "link", "manifest"])
def test_rejects_unreviewed_or_mismatched_source_before_install_or_pointer(setup, bad):
    m, args, _, _, _, _, _, pack = setup
    if bad == "hash":
        args[7] = "f" * 64
    elif bad == "identity":
        pack(identity="b" * 40)
    elif bad == "controller":
        pack(changed="fhd-auto-update.sh")
    elif bad == "link":
        pack(link="fhd-auto-update.sh")
    else:
        p = Path(args[0]) / "fhd-manifest.json"
        d = json.loads(p.read_text())
        d["git_sha"] = "b" * 40
        p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_same_legacy_flock_blocks_upgrade_and_manifest(setup):
    m, args, *_ = setup
    with m.LOCK_PATH.open("a+") as old:
        fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="lock timeout"):
            m.bootstrap_promote(args)
    unchanged(setup)


def test_already_loaded_legacy_process_must_exit_or_install_rolls_back(setup):
    m, args, _, deploy, *_ = setup
    proc = m.PROC_ROOT / "123"
    proc.mkdir()
    (proc / "cmdline").write_bytes(b"bash\0" + os.fsencode(deploy / "fhd-auto-update.sh") + b"\0")
    with pytest.raises(RuntimeError, match="has not exited"):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_partial_install_failure_rolls_back_existing_controllers(setup, monkeypatch):
    m, args, _, deploy, *_ = setup
    original = m.atomic_bytes
    failed = [False]

    def fail_once(path, data, mode):
        if path == deploy / "fhd-apply-release.sh" and not failed[0]:
            failed[0] = True
            raise OSError("isolated injected install failure")
        return original(path, data, mode)

    monkeypatch.setattr(m, "atomic_bytes", fail_once)
    with pytest.raises(OSError, match="injected"):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_symlink_parent_is_rejected_without_following_it(setup):
    m, args, root, deploy, *_ = setup
    lib = deploy / "lib"
    moved = root / "outside"
    lib.rename(moved)
    lib.symlink_to(moved, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_missing_proc_visibility_blocks_promotion_and_rolls_back(setup):
    m, args, *_ = setup
    m.PROC_ROOT = m.PROC_ROOT / "absent"
    with pytest.raises(RuntimeError, match="quiescence"):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_archive_swap_after_verification_does_not_promote_wrong_bytes(setup, monkeypatch):
    m, args, _, _, channel, *_ = setup

    def swapped(*_):
        Path(args[0], args[2]).write_bytes(b"swapped-after-verification")

    monkeypatch.setattr(m, "wait_legacy_exit", swapped)
    with pytest.raises(RuntimeError, match="archive changed"):
        m.bootstrap_promote(args)
    assert (channel / "fhd-manifest.json").read_bytes() == b"old-pointer"


def test_inventory_comes_from_main_commit_not_dirty_worktree_and_rejects_branch(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env, text=True).strip()

    git("init", "-q")
    for name in NAMES:
        p = repo / "FHD/scripts/deploy" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"# reviewed\n")
    git("add", "FHD/scripts/deploy")
    git("commit", "-qm", "fixture")
    main = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", main)
    body = SCRIPT.read_text().split("<<'PY_CONTROLLERS'\n", 1)[1].split("\nPY_CONTROLLERS", 1)[0]
    p = repo / "FHD/scripts/deploy/fhd-auto-update.sh"
    p.write_bytes(b"# dirty unreviewed\n")
    result = subprocess.run(
        [os.sys.executable, "-c", body, str(repo / "FHD"), main],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    hashes = json.loads(base64.b64decode(result.stdout))
    assert hashes["fhd-auto-update.sh"] == hashlib.sha256(b"# reviewed\n").hexdigest()
    git("commit", "--allow-empty", "-qm", "unmerged fixture")
    branch = git("rev-parse", "HEAD")
    result = subprocess.run(
        [os.sys.executable, "-c", body, str(repo / "FHD"), branch],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_existing_staging_channel_does_not_install_production_controllers(setup):
    m, args, _, deploy, channel, old, _, _ = setup
    args[4] = "staging"
    args[8] = "e30="
    m.bootstrap_promote(args)
    assert all((deploy / name).read_bytes() == data for name, data in old.items())
    assert json.loads((channel / "fhd-manifest.json").read_text())["git_sha"] == SHA
    assert not m.LOCK_PATH.exists()


@pytest.mark.parametrize("inventory", [{}, {"../.env": "a" * 64}])
def test_stable_inventory_cannot_omit_controllers_or_write_other_paths(setup, inventory):
    m, args, *_ = setup
    args[8] = base64.b64encode(json.dumps(inventory).encode()).decode()
    with pytest.raises(RuntimeError, match="inventory"):
        m.bootstrap_promote(args)
    unchanged(setup)


def test_stable_cannot_upgrade_a_different_root_then_promote_for_old_cron(setup):
    m, args, *_ = setup
    args[5] = str(Path(args[5]).parent / "different-runtime")
    with pytest.raises(RuntimeError, match="legacy cron target"):
        m.bootstrap_promote(args)
    unchanged(setup)
