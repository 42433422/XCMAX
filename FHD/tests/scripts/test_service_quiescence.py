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
