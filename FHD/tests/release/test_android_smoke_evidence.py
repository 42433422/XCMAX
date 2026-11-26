"""Host-side regression of emulator smoke control flow (mock adb, not device evidence)."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci/android_smoke.sh"


@pytest.mark.parametrize(
    "mode,expected",
    [("ok", 0), ("stuck", 1), ("crash", 1), ("empty", 1), ("sha_mismatch", 1)],
)
def test_emulator_smoke_rejects_false_positive(tmp_path, mode, expected):
    # Isolate the fixed CI screenshot path; never overwrite a real run's evidence.
    screen = tmp_path / "screen.png"
    screen.write_bytes(b"stale")
    script = tmp_path / "smoke.sh"
    script.write_text(SCRIPT.read_text().replace("/tmp/android-smoke-screen.png", str(screen)))
    apk = tmp_path / "build/app/outputs/flutter-apk/app-debug.apk"
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"mock apk")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "git": "#!/bin/bash\necho aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
        "sleep": "#!/bin/bash\nexit 0\n",
        "adb": """#!/bin/bash
set -eu
printf '%s\\n' "$*" >> "$TEST_TRACE"
case "$*" in
  'shell getprop ro.build.version.release') echo 14 ;;
  'shell getprop ro.product.model') echo 'mock emulator' ;;
  'install -r -g '*) echo Success ;;
  'shell am force-stop '*) touch "$TEST_STATE/stopped" ;;
  'shell pidof '*)
    if [ "$TEST_MODE" = stuck ] || { [ -f "$TEST_STATE/launched" ] && [ "$TEST_MODE" != crash ]; }; then echo 123; else exit 1; fi ;;
  'shell monkey '*) touch "$TEST_STATE/launched" ;;
  'exec-out screencap -p')
    if [ "$TEST_MODE" != empty ]; then printf '\\211PNG\\r\\n\\032\\nmock'; fi ;;
  'logcat -d -t 400') echo FATAL ;;
  *) exit 3 ;;
esac
""",
    }
    for name, content in commands.items():
        executable = bin_dir / name
        executable.write_text(content)
        executable.chmod(0o755)
    trace = tmp_path / "trace"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        APP_PACKAGE="test.app",
        GITHUB_SHA=("b" if mode == "sha_mismatch" else "a") * 40,
        TEST_MODE=mode,
        TEST_STATE=str(tmp_path),
        TEST_TRACE=str(trace),
    )
    result = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert screen.exists() is (mode == "ok")
    if mode == "ok":
        assert "apk_sha256=" in result.stdout and "screenshot_sha256=" in result.stdout
        assert "not_physical_acceptance" in result.stdout
        assert "started_at=" in result.stdout and "ended_at=" in result.stdout
        actions = trace.read_text()
        assert actions.index("shell am force-stop") < actions.index("shell monkey")
    else:
        assert "emulator startup smoke passed" not in result.stdout
