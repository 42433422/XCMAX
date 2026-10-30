"""Exercise failure receipts using workflow shell code and local transport stubs."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def steps(path, job):
    return yaml.safe_load((ROOT / path).read_text())["jobs"][job]["steps"]


def stub(path, body):
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o700)


def run(script, env):
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, timeout=15)


def health(runtime=True):
    return (
        json.dumps(
            {
                "ok": True,
                "data": {
                    "scheduler_running": True,
                    "registration_complete": True,
                    "runtime_healthy": runtime,
                    "pending_job_count": 60,
                    "missing_required_jobs": [],
                    "unhealthy_runtime_jobs": [] if runtime else ["loop"],
                },
            }
        )
        + "\n__HTTP_CODE__200"
    )


@pytest.mark.parametrize(
    "transport,dry,before,after,restart_exit,expected,restarted",
    [
        ("fail", "false", health(), health(), "0", "unknown", "unknown"),
        ("empty", "false", health(), health(), "0", "unknown", "unknown"),
        ("ok", "true", health(False), health(), "0", "unhealthy", "false"),
        ("ok", "false", health(), health(), "0", "healthy", "false"),
        ("ok", "false", health(False), health(), "0", "healthy", "true"),
        ("ok", "false", health(False), health(False), "0", "unhealthy", "true"),
        ("ok", "false", health(False), '{"ok":true}\n__HTTP_CODE__200', "0", "unhealthy", "true"),
        ("ok", "false", health(False), health(), "1", "unknown", "false"),
    ],
)
def test_watchdog_never_closes_without_independent_health(
    tmp_path, transport, dry, before, after, restart_exit, expected, restarted
):
    workflow_steps = steps(".github/workflows/scheduler-watchdog.yml", "probe-and-restart")
    probe = next(s for s in workflow_steps if s.get("id") == "probe")
    close = next(s for s in workflow_steps if s.get("name") == "Close incident on recovery")
    assert "inputs.dry_run != true" in close["if"]
    assert "steps.probe.outputs.health == 'healthy'" in close["if"]
    assert "steps.probe.outputs.restart_triggered == 'false'" in close["if"]
    update = next(s for s in workflow_steps if s.get("name") == "Open or update incident issue")
    assert "inputs.dry_run != true" in update["if"]
    stub(
        tmp_path / "ssh",
        """
    [ "$TRANSPORT" != fail ] || exit 255
    [ "$TRANSPORT" != empty ] || exit 0
    exec bash -s
    """,
    )
    stub(
        tmp_path / "curl",
        """
    if [ -e "$RUNNER_TEMP/restarted" ]; then printf '%s' "$AFTER"; else printf '%s' "$BEFORE"; fi
    """,
    )
    stub(tmp_path / "systemctl", 'touch "$RUNNER_TEMP/restarted"\nexit "$RESTART_EXIT"\n')
    stub(tmp_path / "sleep", "exit 0\n")
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "FHD_PUSH_SSH_KEY_RAW": "test key",
        "FHD_PUSH_HOST": "example.invalid",
        "HEALTH_URL": "http://example.invalid",
        "SERVICE_NAME": "example",
        "CURL_TIMEOUT": "1",
        "DRY_RUN": dry,
        "TRANSPORT": transport,
        "BEFORE": before,
        "AFTER": after,
        "RESTART_EXIT": restart_exit,
    }
    result = run(probe["run"], env)
    assert result.returncode == 0, result.stderr
    output = (tmp_path / "output").read_text().splitlines()
    assert f"health={expected}" in output and f"restart_triggered={restarted}" in output
    assert not (tmp_path / "scheduler_watchdog_key").exists()
    if dry == "true":
        assert not (tmp_path / "restarted").exists()


@pytest.mark.parametrize("failure", ["readiness", "query", "query_payload"])
def test_slo_closes_opened_tunnel_when_probe_retries_fail(tmp_path, failure):
    workflow_steps = steps("FHD/.github/workflows/slo-metrics-collect.yml", "collect")
    opening = next(s for s in workflow_steps if s.get("id") == "prometheus_tunnel")
    closing = next(
        s for s in workflow_steps if s.get("name") == "Close production Prometheus SSH tunnel"
    )
    assert closing["if"] == "always()"
    stub(
        tmp_path / "ssh",
        """
    if [[ " $* " == *" -O exit "* ]]; then
      echo closed >> "$RUNNER_TEMP/trace"
    else
      echo opened >> "$RUNNER_TEMP/trace"
    fi
    """,
    )
    stub(
        tmp_path / "curl",
        """
    echo probe >> "$RUNNER_TEMP/probes"
    [ "$FAILURE" != readiness ] || exit 56
    [[ " $* " == *"/-/ready"* ]] && exit 0
    [ "$FAILURE" != query ] || exit 56
    echo '{"status":"error"}'
    """,
    )
    stub(tmp_path / "sleep", "exit 0\n")
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_ENV": str(tmp_path / "env"),
        "FHD_PUSH_HOST": "example.invalid",
        "FHD_PUSH_SSH_KEY_RAW": "test key",
        "PRODUCTION_PROMETHEUS_URL": "http://127.0.0.1:19091",
        "PRODUCTION_PROMETHEUS_TOKEN": "test token",
        "FAILURE": failure,
    }
    result = run(opening["run"], env)
    assert result.returncode == 1, result.stderr
    assert b"Prometheus tunnel query probe failed after retries" in result.stdout
    assert len((tmp_path / "probes").read_text().splitlines()) == (
        5 if failure == "readiness" else 10
    )
    env.update(line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines())
    assert run(closing["run"], env).returncode == 0
    assert (tmp_path / "trace").read_text().splitlines() == ["opened", "closed"]
    assert not (tmp_path / "fhd_prometheus_metrics_key").exists()
