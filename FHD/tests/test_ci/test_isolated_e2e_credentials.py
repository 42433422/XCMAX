"""The browser gate uses ephemeral credentials, ports and data only."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "FHD/scripts/dev/e2e-full.sh"


def isolated_run(*, final_status=0, **overrides):
    script = SCRIPT.read_text().split("owns_listener()", 1)[0]
    script = script.replace('SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"', f'SCRIPT_DIR="{SCRIPT.parent}"')
    script += '''
"${PY}" - <<'CHECK'
import hashlib, json, os, secrets, socket
from urllib.parse import urlparse
from app.application.surface_audit_demo_account import try_local_demo_market_login
password = os.environ['E2E_PASSWORD']
user = os.environ['E2E_USER']
assert len(password) >= 40
assert password == os.environ['SURFACE_AUDIT_DEMO_PASSWORD']
assert password != 'caller-supplied-placeholder'
valid = try_local_demo_market_login(user, password)
assert valid and valid['success'] and not valid['is_market_admin']
assert try_local_demo_market_login(user, secrets.token_urlsafe(32)) is None
url = urlparse(os.environ['XCAGI_MARKET_BASE_URL'])
assert url.hostname == '127.0.0.1'
assert os.environ['XCAGI_USE_REMOTE_MARKET'] == os.environ['XCAGI_USE_LOCAL_MARKET'] == '0'
assert os.environ['DATABASE_URL'] == os.environ['VECTOR_DB_URL'] == ''
for name in ('HTTPS_PROXY', 'XCAGI_DESKTOP_DATABASE_URL', 'XCAGI_DESKTOP_VECTOR_DB_URL',
             'XCAGI_WORKSPACE_ROOT', 'XCAGI_MODS_ROOT'):
    assert name not in os.environ
with socket.socket() as probe:
    assert probe.connect_ex((url.hostname, url.port)) != 0
with socket.socket() as probe:
    try:
        probe.bind((url.hostname, url.port))
    except OSError:
        pass
    else:
        raise AssertionError('market port not reserved')
# Only non-secret diagnostics cross the subprocess boundary, even on failure.
print(json.dumps({'fingerprint': hashlib.sha256(password.encode()).hexdigest(),
                  'data_dir': os.environ['XCAGI_DATA_DIR']}))
CHECK
'''
    script += f"\nexit {final_status}\n"
    return subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "E2E_PYTHON": sys.executable, "GITHUB_ACTIONS": "false", **overrides},
        capture_output=True, text=True,
    )


def test_random_credentials_are_private_and_isolated():
    runs = [isolated_run() for _ in range(2)]
    assert all(run.returncode == 0 for run in runs)
    first, second = [json.loads(run.stdout) for run in runs]
    assert first["fingerprint"] != second["fingerprint"]
    for result in (first, second):
        assert not Path(result["data_dir"]).exists()


@pytest.mark.parametrize("override", [{"E2E_REUSE_SERVICES": "1"}, {"E2E_DATA_DIR": "/must-not-touch"}])
def test_existing_services_and_data_are_rejected(override):
    result = isolated_run(**override)
    assert result.returncode != 0
    assert "Refusing service/data reuse" in result.stderr


def test_caller_cannot_redirect_credentials_or_data():
    result = isolated_run(
        XCAGI_MARKET_BASE_URL="https://example.invalid", XCAGI_USE_REMOTE_MARKET="1",
        HTTPS_PROXY="https://example.invalid", DATABASE_URL="postgresql://example.invalid/db",
        E2E_PASSWORD="caller-supplied-placeholder",
        XCAGI_DESKTOP_DATABASE_URL="postgresql://example.invalid/db",
        XCAGI_DESKTOP_VECTOR_DB_URL="postgresql://example.invalid/db",
        XCAGI_WORKSPACE_ROOT="/must-not-touch", XCAGI_MODS_ROOT="/must-not-touch",
    )
    assert result.returncode == 0


@pytest.mark.parametrize("port", ["0", "65536", "80@external.invalid", "invalid"])
def test_invalid_endpoint_ports_fail_closed(port):
    assert isolated_run(E2E_API_PORT=port).returncode != 0


def test_failure_removes_private_data_and_preserves_failure_status():
    result = isolated_run(final_status=17)
    assert result.returncode == 17
    assert not Path(json.loads(result.stdout)["data_dir"]).exists()


def test_workflow_does_not_publish_credentials_or_auth_artifacts():
    workflow = yaml.safe_load((ROOT / ".github/workflows/e2e-playwright-reusable.yml").read_text())
    steps = workflow["jobs"]["playwright"]["steps"]
    actual = next(step for step in steps if step.get("run") == "bash ../scripts/dev/e2e-full.sh")
    assert "E2E_PASSWORD" not in actual["env"]
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact"))
    assert upload["with"]["path"].strip() == "${{ runner.temp }}/xcagi-e2e-evidence/*.png"
    source = SCRIPT.read_text()
    assert source.index("set +x") < source.index("secrets.token_urlsafe")
    assert '::add-mask::%s' in source
    assert '"${E2E_DATA_DIR}/first-login"' in source
    assert '"${E2E_DATA_DIR}/erp"' in source
    helper = (ROOT / "FHD/frontend/e2e/helpers.ts").read_text()
    assert "!E2E_USER || !E2E_PASSWORD" in helper


@pytest.mark.parametrize("service_alive, guard_alive", [(False, True), (True, False), (False, False), (True, True)])
def test_health_response_cannot_replace_owned_processes(service_alive, guard_alive):
    source = SCRIPT.read_text()
    start = source.index("wait_http()")
    function = source[start:source.index('\nif curl --noproxy', start)]
    service = "$$" if service_alive else "99999999"
    guard = "$$" if guard_alive else "99999999"
    result = subprocess.run(
        ["bash", "-c", f'''set -e
log() {{ :; }}
fail() {{ exit 1; }}
curl() {{ return 0; }}
owns_listener() {{ return 0; }}
MARKET_GUARD_PID={guard}
{function}
wait_http http://127.0.0.1:12345 test {service} 1
'''], capture_output=True,
    )
    assert (result.returncode == 0) == (service_alive and guard_alive)


def test_socket_ownership_rejects_unrelated_live_process():
    import socket

    source = SCRIPT.read_text()
    function = source[source.index("owns_listener()"):source.index("wait_http()")]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        for pid, expected in ((str(os.getpid()), 0), ("$$", 1)):
            result = subprocess.run(
                ["bash", "-c", f'PY="{sys.executable}"\n{function}\nowns_listener {pid} {url}'],
                capture_output=True,
            )
            assert result.returncode == expected


@pytest.fixture
def supervised_services(tmp_path):
    import time

    ready = tmp_path / "ports.json"
    backend = subprocess.Popen([sys.executable, "-c", '''
import json, pathlib, socket, sys, time
sockets = [socket.socket(), socket.socket()]
for sock in sockets:
    sock.bind(('127.0.0.1', 0))
    sock.listen()
pathlib.Path(sys.argv[1]).write_text(json.dumps([s.getsockname()[1] for s in sockets]))
time.sleep(60)
''', str(ready)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    guard = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.02)
        ports = json.loads(ready.read_text())
        args = [sys.executable, str(ROOT / 'FHD/scripts/dev/e2e_supervise.py'),
                str(backend.pid), str(backend.pid), str(guard.pid),
                *(f'http://127.0.0.1:{port}' for port in ports)]
        yield backend, guard, args
    finally:
        for process in (backend, guard):
            if process.poll() is None:
                process.kill()
            process.wait()


@pytest.mark.parametrize("exit_code", [0, 17])
def test_supervision_preserves_suite_result(supervised_services, exit_code):
    backend, guard, args = supervised_services
    result = subprocess.run([*args, sys.executable, '-c', f'raise SystemExit({exit_code})'])
    assert result.returncode == exit_code
    assert backend.poll() is None and guard.poll() is None


def test_guard_death_between_suites_prevents_second_command(supervised_services, tmp_path):
    backend, guard, args = supervised_services
    assert subprocess.run([*args, sys.executable, '-c', 'pass']).returncode == 0
    guard.kill()
    guard.wait()
    marker = tmp_path / 'must-not-run'
    result = subprocess.run([*args, sys.executable, '-c',
                             'import pathlib, sys; pathlib.Path(sys.argv[1]).touch()', str(marker)])
    assert result.returncode != 0
    assert not marker.exists()
    # The shell also cleans up; supervision must itself stop credential handling.
    assert backend.wait(timeout=5) != 0


def test_guard_death_during_suite_stops_backend_and_browser(supervised_services, tmp_path):
    import time

    backend, guard, args = supervised_services
    marker = tmp_path / 'running'
    suite = subprocess.Popen([*args, sys.executable, '-c',
                              'import pathlib, os, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',
                              str(marker)])
    try:
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.02)
        browser_pid = int(marker.read_text())
        guard.kill()
        guard.wait()
        assert suite.wait(timeout=5) != 0
        assert backend.wait(timeout=5) != 0
        import psutil
        assert not psutil.pid_exists(browser_pid)
    finally:
        if suite.poll() is None:
            suite.kill()
        suite.wait()


@pytest.mark.parametrize("parent_exits", [False, True])
def test_detached_browser_is_stopped_even_after_parent_exit(supervised_services, tmp_path, parent_exits):
    import time

    import psutil

    backend, guard, args = supervised_services
    marker = tmp_path / 'detached-browser'
    suite = subprocess.Popen([*args, sys.executable, '-c', '''
import pathlib, subprocess, sys, time
browser = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
pathlib.Path(sys.argv[1]).write_text(str(browser.pid))
if sys.argv[2] != 'exit':
    time.sleep(60)
raise SystemExit(17)
''', str(marker), 'exit' if parent_exits else 'wait'])
    browser = None
    try:
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.02)
        browser = psutil.Process(int(marker.read_text()))
        if not parent_exits:
            guard.kill()
            guard.wait()
        assert suite.wait(timeout=8) != 0
        if not parent_exits:
            assert backend.wait(timeout=5) != 0
        else:
            assert backend.poll() is None and guard.poll() is None
        stopped = not browser.is_running() or browser.status() == psutil.STATUS_ZOMBIE
        assert stopped
    finally:
        if suite.poll() is None:
            suite.kill()
        suite.wait()
        if browser is not None:
            try:
                browser.kill()
            except psutil.Error:
                pass


@pytest.mark.parametrize('unsupported_platform', [False, True])
def test_missing_subreaper_support_fails_closed(supervised_services, tmp_path, unsupported_platform):
    backend, _guard, args = supervised_services
    marker = tmp_path / 'must-not-run'
    code = '''
import ctypes, runpy, sys, types
module = runpy.run_path(sys.argv[1])
if sys.argv[2] == 'unsupported':
    sys.platform = 'unsupported'
else:
    class Denied:
        def __call__(self, *args):
            return -1
    ctypes.CDLL = lambda *args, **kwargs: types.SimpleNamespace(prctl=Denied())
raise SystemExit(module['run'](int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]),
                              sys.argv[6], sys.argv[7], sys.argv[8:]))
'''
    result = subprocess.run([sys.executable, '-c', code, args[1],
                             'unsupported' if unsupported_platform else 'denied', *args[2:],
                             sys.executable, '-c',
                             'import pathlib, sys; pathlib.Path(sys.argv[1]).touch()', str(marker)])
    assert result.returncode != 0
    assert not marker.exists()
    assert backend.wait(timeout=5) != 0
