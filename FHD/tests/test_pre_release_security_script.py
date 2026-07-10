from __future__ import annotations

import re
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = FHD_ROOT / "scripts" / "package" / "pre-release-security.ps1"


def _quoted_values(block_name: str, script: str) -> set[str]:
    match = re.search(rf"\${block_name}\s*=\s*@\((.*?)\)", script, re.DOTALL)
    assert match, f"missing ${block_name} in {SCRIPT}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_secret_scanner_exempts_source_code_names() -> None:
    script = SCRIPT.read_text(encoding="utf-8-sig")
    source_extensions = _quoted_values("sourceExtensions", script)

    assert ".py" in source_extensions
    assert ".ps1" in source_extensions
    assert ".ts" in source_extensions
    assert "$extension -notin $sourceExtensions" in script
    assert (
        FHD_ROOT
        / "mods"
        / "_employees"
        / "security-secrets-guard"
        / "backend"
        / "employees"
        / "security_secrets_guard.py"
    ).is_file()


def test_secret_scanner_still_covers_private_material() -> None:
    script = SCRIPT.read_text(encoding="utf-8-sig")
    private_extensions = _quoted_values("privateMaterialExtensions", script)

    assert {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"} <= private_extensions
    assert "$isDotEnv" in script
    assert "client[_-]?secret" in script
    assert "private[_-]?key" in script
