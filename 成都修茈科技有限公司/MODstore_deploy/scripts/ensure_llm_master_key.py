"""Ensure the BYOK Fernet master key exists in the deployment .env file.

The key must be stable across restarts because user BYOK values are encrypted
with it before being stored in the database.
"""

from __future__ import annotations

import base64
import os
import re
import stat
import sys
from pathlib import Path


KEY_NAME = "MODSTORE_LLM_MASTER_KEY"
ASSIGN_RE = re.compile(rf"^\s*(?:export\s+)?{re.escape(KEY_NAME)}\s*=", re.ASCII)


def _generate_fernet_key() -> str:
    # Fernet keys are 32 url-safe base64-encoded random bytes.
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _is_valid_fernet_key(value: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(value.encode("ascii"))) == 32
    except Exception:
        return False


def ensure_key(env_path: Path) -> bool:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()

    for idx, line in enumerate(lines):
        if not ASSIGN_RE.match(line):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        if value and _is_valid_fernet_key(value):
            print(f"[OK] {KEY_NAME} 已配置")
            return False
        if value:
            raise ValueError(f"{KEY_NAME} 已存在但不是有效 Fernet 密钥，请手动核对后再部署")
        lines[idx] = f"{KEY_NAME}={_generate_fernet_key()}"
        _write_env(env_path, lines)
        print(f"[OK] 已生成并写入 {KEY_NAME}")
        return True

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(
        [
            "# BYOK 加密主密钥；生成后必须保持稳定，避免已保存密钥无法解密。",
            f"{KEY_NAME}={_generate_fernet_key()}",
        ],
    )
    _write_env(env_path, lines)
    print(f"[OK] 已生成并写入 {KEY_NAME}")
    return True


def _write_env(env_path: Path, lines: list[str]) -> None:
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        current = env_path.stat().st_mode
        env_path.chmod(current & ~(stat.S_IRWXG | stat.S_IRWXO))
    except OSError:
        pass


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    env_path = Path(argv[1]).expanduser() if len(argv) > 1 else root / ".env"
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()
    ensure_key(env_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
