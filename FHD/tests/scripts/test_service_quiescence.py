import re
import shlex
import subprocess
from pathlib import Path

import pytest


def test_service_and_failed_rollback_recovery():
    result = subprocess.run(
        ["bash", str(Path(__file__).with_name("service_quiescence_mock.sh"))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mode,status", [("ok", 0), ("deny_rollback", 77), ("deny_restart", 78), ("stop_fails", 79)]
)
def test_real_rollback_checks_both_gates_and_stops_writes_first(tmp_path, mode, status):
    deploy = Path(__file__).resolve().parents[2] / "scripts/deploy"
    source = (deploy / "fhd-apply-release.sh").read_text()
    rollback = re.search(r"^rollback_from_backup\(\) \{\n.*?^\}", source, re.M | re.S)
    assert rollback is not None
    root, backup, trace = tmp_path / "runtime", tmp_path / "backup", tmp_path / "trace"
    root.mkdir()
    (backup / "app").mkdir(parents=True)
    script = "\n".join(
        [
            "set -euo pipefail",
            f"source {shlex.quote(str(deploy / 'lib/service_quiescence.sh'))}",
            f"source {shlex.quote(str(deploy / 'lib/apply_recovery.sh'))}",
            f"DEPLOY_ROOT={shlex.quote(str(root))} BACKUP={shlex.quote(str(backup))}",
            f"TRACE={shlex.quote(str(trace))} MODE={shlex.quote(mode)}",
            f"MODS_UPDATE_STATE={shlex.quote(str(tmp_path / 'no-mod-transaction'))}",
            "SERVICE=fixture.service TARBALL_SHA256=" + "a" * 64,
            "ADMIN_BACKUP_PRESENT=0 MOCK_STATE=active",
            "log() { :; }",
            """autonomy_evaluate_action() {
          printf 'gate:%s\\n' "$1" >> "$TRACE"
          if [[ "$MODE" == deny_rollback && "$1" == rollback_release ]]; then return 77; fi
          if [[ "$MODE" == deny_restart && "$1" == restart_service ]]; then return 78; fi
          return 0
        }""",
            """systemctl() {
          printf '%s\\n' "$1" >> "$TRACE"
          case "$1" in
            show) printf '%s\\n' "$MOCK_STATE" ;;
            stop) [[ "$MODE" != stop_fails ]] || return 79; MOCK_STATE=inactive ;;
            restart) MOCK_STATE=active ;;
            is-active) [[ "$MOCK_STATE" == active ]] ;;
            *) return 90 ;;
          esac
        }""",
            """rsync() {
          [[ "$MOCK_STATE" == inactive ]] || return 91
          printf 'mutate\\n' >> "$TRACE"
        }""",
            rollback.group(0),
            # Conditional calls suppress Bash errexit inside functions; explicit
            # propagation must still prevent mutations after an authorization error.
            "if rollback_from_backup; then exit 0; else exit $?; fi",
        ]
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == status, result.stderr
    events = trace.read_text().splitlines()
    if status:
        assert "mutate" not in events and "restart" not in events
    else:
        assert events.index("gate:rollback_release") < events.index("gate:restart_service")
        assert events.index("stop") < events.index("mutate") < events.index("restart")


@pytest.mark.parametrize("rollback_status,copy_fails", [(0, False), (1, False), (1, True)])
def test_real_cleanup_preserves_failed_apply_transaction(tmp_path, rollback_status, copy_fails):
    deploy = Path(__file__).resolve().parents[2] / "scripts/deploy"
    source = (deploy / "fhd-apply-release.sh").read_text()
    cleanup = re.search(r"^cleanup_apply\(\) \{\n.*?^\}", source, re.M | re.S)
    assert cleanup is not None
    workspace = tmp_path / "apply"
    state = workspace / "mods-update-state"
    state.mkdir(parents=True)
    (state / "plan.json").write_text("preserve original transaction")
    backup = tmp_path / "backup"
    backup.mkdir()
    script = "\n".join(
        [
            "set -euo pipefail",
            f"source {shlex.quote(str(deploy / 'lib/apply_recovery.sh'))}",
            cleanup.group(0),
            "log() { :; }",
            f"rollback_from_backup() {{ return {rollback_status}; }}",
            "cp() { return 1; }" if copy_fails else ":",
            f"TMP={shlex.quote(str(workspace))}",
            f"MODS_UPDATE_STATE={shlex.quote(str(state))}",
            f"BACKUP={shlex.quote(str(backup))}",
            "TS=test MUTATION_STARTED=1 ROLLBACK_DONE=0 ROLLBACK_CONFIRMED=0",
            "FHD_SERVICE_STOP_ATTEMPTED=0 FHD_SERVICE_WAS_ACTIVE=0",
            "trap cleanup_apply EXIT",
            "false",
        ]
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    if copy_fails:
        assert (state / "plan.json").read_text() == "preserve original transaction"
    else:
        assert not workspace.exists()
        recovery = backup / "recovery-test/mods-update-state/plan.json"
        assert recovery.read_text() == "preserve original transaction"
        assert (backup / ".recovery-required").is_file()
