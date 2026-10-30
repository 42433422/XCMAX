"""Historical Gitleaks exceptions may not suppress real or unverified credentials.

Exact fingerprints do not make historical credentials synthetic. Accepted-risk
incident decisions are tracked independently and must not silently disable
historical secret scanning.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IGNORE = ROOT / ".gitleaksignore"
INCIDENTS = ROOT / ".github" / "security" / "credential-incidents.json"
FINGERPRINT = re.compile(
    r"(?P<commit>[0-9a-f]{40}):(?P<path>.+):(?P<rule>[a-z0-9-]+):(?P<line>[1-9][0-9]*)"
)


def _exceptions() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for number, raw in enumerate(IGNORE.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = FINGERPRINT.fullmatch(line)
        assert match is not None, (
            f".gitleaksignore:{number}: fingerprint must be commit:file:rule:line"
        )
        entries.append((line, match.group("path")))
    return entries


def test_gitleaks_exceptions_are_exact_and_unique() -> None:
    fingerprints = [entry for entry, _ in _exceptions()]
    assert len(fingerprints) == len(set(fingerprints)), "duplicate Gitleaks exemptions"


def test_credential_incident_sources_are_not_silenced() -> None:
    register = json.loads(INCIDENTS.read_text(encoding="utf-8"))
    incident_paths = {
        source
        for incident in register["incidents"]
        for source in incident["source_locations"]
    }
    for _, path in _exceptions():
        assert path not in incident_paths, (
            "historical credential incident requires separate remediation/review: " + path
        )


def test_historical_secrets_and_unverified_assets_still_scan() -> None:
    for _, path in _exceptions():
        assert re.search(r"(^|/)\.env($|[.-])", path) is None, path
        assert not path.endswith("/mobile_relay_desktop.json"), path
        assert path != "deploy_staging.sh", path
        assert "/assets/js/" not in path, path
        assert "/corp-butler/assets/" not in path, path
