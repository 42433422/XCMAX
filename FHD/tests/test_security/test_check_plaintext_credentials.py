"""credential-guard：拦新增明文凭据，输出不含值，占位符与引用放行。"""

from __future__ import annotations

import importlib.util
import secrets
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "check_plaintext_credentials",
    REPO_ROOT / "FHD" / "scripts" / "security" / "check_plaintext_credentials.py",
)
assert _SPEC and _SPEC.loader
guard = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = guard
_SPEC.loader.exec_module(guard)


def _pw() -> str:
    return "Pw" + secrets.token_hex(5) + "!"


def _rules(path: str, line: str) -> list[str]:
    return [f.rule for f in guard.scan_added_lines([(path, 1, line)])]


def test_blocks_plaintext_defaults_and_assignments():
    value = _pw()
    assert _rules("app/x.py", f'PASS = os.environ.get("X_ADMIN_PASSWORD", "{value}")') == [
        "env-default-literal"
    ]
    assert _rules("a.mjs", f"const p = process.env.X_PASSWORD || '{value}'") == [
        "js-env-fallback-literal"
    ]
    assert _rules("run.sh", f'export X_PASSWORD="${{X_PASSWORD:-{value}}}"') == [
        "shell-default-literal"
    ]
    assert _rules("deploy.sh", f"sshpass -p '{value}' ssh host") == ["cli-password-literal"]
    assert _rules("cfg.json", f'"password": "{value}",') == ["password-assign-literal"]
    assert _rules("acc.ps1", f"[string]$Password = '{value}',") == ["password-assign-literal"]
    assert _rules("doc.md", f'API_TOKEN = "{secrets.token_hex(10)}"') == ["secret-assign-literal"]


def test_allows_references_placeholders_and_markers():
    allowed = [
        'token = os.environ.get("X_API_TOKEN", "")',
        'PASS = os.environ.get("X_PASSWORD")',
        "const p = process.env.X_PASSWORD || ''",
        'export X_PASSWORD="${X_PASSWORD:-}"',
        'export X_PASSWORD="${X_PASSWORD:-<from-vault>}"',
        'WEAK_PASSWORD = "weak_password"',
        'raw = os.environ.get("X_CREDENTIAL_SCOPES", "OPENAI_API_KEY,CODEX_API_KEY")',
        '"password": "password",',
        '"password": "changeme",',
        'n = int(os.environ.get("X_TOKEN_ESTIMATE", "1000"))',
        f'"password": "{_pw()}",  # credential-guard: allow',
        'password = get_credential("X_PASSWORD", task_id=t, purpose=p)',
    ]
    for line in allowed:
        assert _rules("app/x.py", line) == [], line


def test_tests_and_lockfiles_are_out_of_scope():
    line = f'"password": "{_pw()}"'
    assert _rules("FHD/tests/test_x.py", line) == []
    assert _rules("pkg/package-lock.json", line) == []
    assert _rules("tools/a.test.mjs", line) == []


def test_cli_output_never_prints_value(tmp_path, capsys):
    value = _pw()
    target = tmp_path / "leak.sh"
    target.write_text(f'export X_PASSWORD="${{X_PASSWORD:-{value}}}"\n', encoding="utf-8")
    assert guard.main(["--files", str(target)]) == 1
    captured = capsys.readouterr()
    assert value not in captured.out + captured.err
    assert "shell-default-literal" in captured.out


def test_git_range_scans_only_added_lines(tmp_path, monkeypatch):
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "old.py").write_text(
        f'PW = os.environ.get("A_PASSWORD", "{_pw()}")\n', encoding="utf-8"
    )
    git("add", ".")
    git("commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "new.py").write_text('PW = os.environ.get("A_PASSWORD", "")\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "clean")
    monkeypatch.chdir(tmp_path)
    added = guard._git_added_lines(base, "HEAD")
    assert [p for p, _, _ in added] == ["new.py"]
    assert guard.scan_added_lines(added) == []
