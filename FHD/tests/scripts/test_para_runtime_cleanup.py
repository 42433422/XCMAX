from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
CLEANUP_SCRIPT = FHD_ROOT / "scripts" / "dev" / "para_runtime_cleanup.sh"
WATCHDOG_SCRIPT = FHD_ROOT / "scripts" / "dev" / "para_health_watchdog.sh"
INSTALL_SCRIPT = FHD_ROOT / "scripts" / "dev" / "install_para_health_watchdog.sh"


def _runtime(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    api_root = tmp_path / "runtime" / "devfleet"
    archive_dir = api_root / "api" / "data" / "cleanup-archives"
    log_dir = tmp_path / "runtime" / "logs"
    workspace_root = tmp_path / "workspaces"
    cleanup_program = api_root / "scripts" / "cleanup-expired-info.mjs"
    fake_node = tmp_path / "fake-node"
    marker = tmp_path / "node-args"

    archive_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    cleanup_program.parent.mkdir(parents=True)
    cleanup_program.write_text("// test stub\n", encoding="utf-8")
    fake_node.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$PARA_TEST_NODE_ARGS"\n',
        encoding="utf-8",
    )
    fake_node.chmod(0o755)

    env = {
        **os.environ,
        "PARA_API_ROOT": str(api_root),
        "PARA_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "PARA_NODE_BIN": str(fake_node),
        "PARA_CLEANUP_SCRIPT": str(cleanup_program),
        "PARA_CLEANUP_ARCHIVE_DIR": str(archive_dir),
        "PARA_LOG_DIR": str(log_dir),
        "PARA_WORKSPACE_ROOT": str(workspace_root),
        "PARA_CLEANUP_LOCK_DIR": str(tmp_path / "runtime" / "cleanup.lock"),
        "PARA_CLEANUP_ARCHIVE_KEEP": "2",
        "PARA_TEST_NODE_ARGS": str(marker),
        "XCMAX_WORKTREE_GC_ENABLED": "0",
        "XCMAX_EPHEMERAL_GC_ENABLED": "0",
    }
    return env, archive_dir, log_dir, workspace_root


def _age(path: Path, *, days: int = 0, minutes: int = 0) -> None:
    seconds = days * 86_400 + minutes * 60
    timestamp = time.time() - seconds
    os.utime(path, (timestamp, timestamp))


def test_apply_prunes_archives_logs_and_stale_uuid_workspaces(tmp_path: Path) -> None:
    env, archive_dir, log_dir, workspace_root = _runtime(tmp_path)
    for index in range(4):
        (archive_dir / f"devfleet-2026-01-0{index + 1}.db").write_text(
            str(index),
            encoding="utf-8",
        )
        (archive_dir / f"cleanup-2026-01-0{index + 1}.json").write_text(
            str(index),
            encoding="utf-8",
        )
    old_log = log_dir / "old.log"
    old_log.write_text("old", encoding="utf-8")
    _age(old_log, days=9)
    current_log = log_dir / "current.log"
    current_log.write_text("current", encoding="utf-8")

    stale_uuid = workspace_root / "12345678-1234-task"
    stale_uuid.mkdir()
    _age(stale_uuid, minutes=180)
    unrelated = workspace_root / "keep-user-folder"
    unrelated.mkdir()
    _age(unrelated, minutes=180)

    result = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--apply", "--reason", "test"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in archive_dir.glob("*.db")) == [
        "devfleet-2026-01-03.db",
        "devfleet-2026-01-04.db",
    ]
    assert sorted(path.name for path in archive_dir.glob("*.json")) == [
        "cleanup-2026-01-03.json",
        "cleanup-2026-01-04.json",
    ]
    assert not old_log.exists()
    assert current_log.exists()
    assert not stale_uuid.exists()
    assert unrelated.exists()
    node_args = Path(env["PARA_TEST_NODE_ARGS"]).read_text(encoding="utf-8")
    assert "--apply" in node_args
    assert "--retention-days" in node_args
    assert "--no-vacuum" in node_args


def test_default_is_dry_run_and_keeps_files(tmp_path: Path) -> None:
    env, archive_dir, log_dir, workspace_root = _runtime(tmp_path)
    backup = archive_dir / "devfleet-2026-01-01.db"
    backup.write_text("backup", encoding="utf-8")
    old_log = log_dir / "old.log"
    old_log.write_text("old", encoding="utf-8")
    _age(old_log, days=9)
    stale_uuid = workspace_root / "12345678-1234-task"
    stale_uuid.mkdir()
    _age(stale_uuid, minutes=180)

    result = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert backup.exists()
    assert old_log.exists()
    assert stale_uuid.exists()
    node_args = Path(env["PARA_TEST_NODE_ARGS"]).read_text(encoding="utf-8")
    assert "--apply" not in node_args


def test_cleanup_rejects_broad_delete_targets(tmp_path: Path) -> None:
    env, _, _, _ = _runtime(tmp_path)
    env["PARA_LOG_DIR"] = "/"

    result = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--apply"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "拒绝不受限的日志目录" in result.stdout


def test_watchdog_and_installer_wire_low_disk_cleanup() -> None:
    watchdog = WATCHDOG_SCRIPT.read_text(encoding="utf-8")
    installer = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "PARA_DISK_MIN_AVAILABLE_KB" in watchdog
    assert "maybe_cleanup_disk" in watchdog
    assert "--reason low-disk" in watchdog
    assert "com.xcmax.para-cleanup.plist" in installer
    assert "PARA_CLEANUP_COMMAND" in installer


def test_watchdog_triggers_cleanup_below_watermark_and_respects_cooldown(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_df = bin_dir / "df"
    fake_df.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        'printf "%s\\n" "test 100000 99000 1000 99% /"\n',
        encoding="utf-8",
    )
    fake_df.chmod(0o755)

    marker = tmp_path / "cleanup-calls"
    cleanup = tmp_path / "cleanup"
    cleanup.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$PARA_TEST_CLEANUP_MARKER"\n',
        encoding="utf-8",
    )
    cleanup.chmod(0o755)

    health_root = tmp_path / "health"
    (health_root / "api").mkdir(parents=True)
    (health_root / "api" / "health").write_text("ok", encoding="utf-8")
    api_root = tmp_path / "api-root"
    api_root.mkdir()
    state_dir = tmp_path / "state"
    log_file = tmp_path / "watchdog.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "PARA_API_URL": health_root.as_uri(),
        "PARA_API_ROOT": str(api_root),
        "PARA_DISK_CHECK_PATH": str(api_root),
        "PARA_DISK_MIN_AVAILABLE_KB": "2000",
        "PARA_CLEANUP_COOLDOWN_SEC": "3600",
        "PARA_CLEANUP_COMMAND": str(cleanup),
        "PARA_TEST_CLEANUP_MARKER": str(marker),
        "PARA_WATCHDOG_STATE_DIR": str(state_dir),
        "PARA_WATCHDOG_LOG_FILE": str(log_file),
    }

    first = subprocess.run(
        ["bash", str(WATCHDOG_SCRIPT), "--once"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    second = subprocess.run(
        ["bash", str(WATCHDOG_SCRIPT), "--once"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    cleanup_calls = marker.read_text(encoding="utf-8").splitlines()
    assert cleanup_calls == ["--apply --reason low-disk"]
    state = (state_dir / "state.env").read_text(encoding="utf-8")
    assert "last_cleanup_epoch=" in state
    assert "低磁盘水位触发有界清理" in log_file.read_text(encoding="utf-8")


def test_apply_removes_only_old_clean_worktree_already_merged_to_main(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _runtime(tmp_path)
    repo = tmp_path / "repo"
    worktree_root = tmp_path / "worktrees"
    worktree = worktree_root / "merged"
    unmerged = worktree_root / "unmerged"
    dirty = worktree_root / "dirty"
    repo.mkdir()
    worktree_root.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "merged-feature", str(worktree)],
        cwd=repo,
        check=True,
    )
    (worktree / "tracked.txt").write_text("merged\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "merged-feature", "-m", "merge"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", "unmerged-feature", str(unmerged)],
        cwd=repo,
        check=True,
    )
    (unmerged / "unmerged.txt").write_text("not on main\n", encoding="utf-8")
    subprocess.run(["git", "add", "unmerged.txt"], cwd=unmerged, check=True)
    subprocess.run(["git", "commit", "-m", "unmerged"], cwd=unmerged, check=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "dirty-feature", str(dirty), "main"],
        cwd=repo,
        check=True,
    )
    (dirty / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    _age(worktree, minutes=10)
    _age(unmerged, minutes=10)
    _age(dirty, minutes=10)

    fake_lsof = tmp_path / "lsof"
    fake_lsof.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_lsof.chmod(0o755)
    env.update(
        {
            "XCMAX_WORKTREE_GC_ENABLED": "1",
            "XCMAX_REPO_ROOT": str(repo),
            "XCMAX_WORKTREE_ROOT": str(worktree_root),
            "XCMAX_WORKTREE_RETENTION_MINUTES": "1",
            "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        }
    )

    result = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--apply", "--reason", "test"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not worktree.exists()
    assert unmerged.exists()
    assert dirty.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", "merged-feature"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "merged-feature" in branches


def test_ephemeral_cleanup_requires_age_name_and_inactivity(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _runtime(tmp_path)
    ephemeral_root = tmp_path / "ephemeral"
    ephemeral_root.mkdir()

    removable = ephemeral_root / "xcmax-qa-old"
    removable.mkdir()
    (removable / "payload.bin").write_bytes(b"x" * 1024)
    _age(removable, minutes=120)

    young = ephemeral_root / "xcmax-qa-young"
    young.mkdir()
    unrelated = ephemeral_root / "keep-user-artifact"
    unrelated.mkdir()
    _age(unrelated, minutes=120)
    active = ephemeral_root / "qa-target-active"
    active.mkdir()
    _age(active, minutes=120)
    opened = ephemeral_root / "sm-qa-open"
    opened.mkdir()
    _age(opened, minutes=120)
    mounted = ephemeral_root / "xcagi-electron-diagnose-mounted"
    mounted.mkdir()
    _age(mounted, minutes=120)
    nested_git = ephemeral_root / "xcmax-review-preserve-git"
    (nested_git / ".git").mkdir(parents=True)
    _age(nested_git, minutes=120)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_lsof = fake_bin / "lsof"
    fake_lsof.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = "-d" ]; then\n'
        '  printf "p1\\nn%s\\n" "$PARA_TEST_ACTIVE_CWD"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$2" = "+D" ] && [ "$3" = "$PARA_TEST_OPEN_DIR" ]; then\n'
        '  printf "p1\\nn%s/open.txt\\n" "$PARA_TEST_OPEN_DIR"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_lsof.chmod(0o755)
    fake_mount = fake_bin / "mount"
    fake_mount.write_text(
        '#!/bin/sh\nprintf "/dev/test on %s (apfs, read-only)\\n" "$PARA_TEST_MOUNT_DIR"\n',
        encoding="utf-8",
    )
    fake_mount.chmod(0o755)
    env.update(
        {
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "XCMAX_EPHEMERAL_GC_ENABLED": "1",
            "XCMAX_EPHEMERAL_ROOT": str(ephemeral_root),
            "XCMAX_EPHEMERAL_RETENTION_MINUTES": "60",
            "PARA_TEST_ACTIVE_CWD": str(active),
            "PARA_TEST_OPEN_DIR": str(opened),
            "PARA_TEST_MOUNT_DIR": str(mounted),
        }
    )

    preview = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--reason", "test-preview"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert preview.returncode == 0, preview.stderr
    assert removable.exists()
    assert "失活非 Git 临时目录 candidates=1" in preview.stdout

    applied = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--apply", "--reason", "test-apply"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    assert not removable.exists()
    assert young.exists()
    assert unrelated.exists()
    assert active.exists()
    assert opened.exists()
    assert mounted.exists()
    assert nested_git.exists()


def test_ephemeral_cleanup_rejects_broad_root(tmp_path: Path) -> None:
    env, _, _, _ = _runtime(tmp_path)
    env.update(
        {
            "XCMAX_EPHEMERAL_GC_ENABLED": "1",
            "XCMAX_EPHEMERAL_ROOT": "/",
        }
    )

    result = subprocess.run(
        ["bash", str(CLEANUP_SCRIPT), "--apply"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "拒绝不安全的临时目录根" in result.stdout
