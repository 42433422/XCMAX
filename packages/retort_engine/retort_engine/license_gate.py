from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

DEFAULT_ALLOWED_LICENSES = ("MIT", "Apache", "BSD", "ISC", "Python")
DEFAULT_BLOCKED_LICENSES = ("GPL", "AGPL", "LGPL", "General Public License", "Affero", "SSPL", "Commons Clause", "BUSL")


@dataclass(frozen=True)
class LicenseGateResult:
    status: str
    detected_license: str
    message: str

    @property
    def passed(self) -> bool:
        return self.status in {"passed", "warning"}

    def to_findings(self) -> tuple[str, ...]:
        return (f"{self.status}: {self.message}",)

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "detected_license": self.detected_license, "message": self.message}


def license_gate(project_path: str | Path, *, enforce: bool = False, allowed: tuple[str, ...] = DEFAULT_ALLOWED_LICENSES, blocked: tuple[str, ...] = DEFAULT_BLOCKED_LICENSES) -> LicenseGateResult:
    detected = detect_license(project_path)
    if not detected:
        return LicenseGateResult("blocked" if enforce else "warning", "", "license-incompatible risk: no LICENSE file detected")
    if any(name.lower() in detected.lower() for name in blocked):
        return LicenseGateResult("blocked", detected, f"license-incompatible risk: blocked license detected: {detected}")
    if any(name.lower() in detected.lower() for name in allowed):
        return LicenseGateResult("passed", detected, f"Allowed license detected: {detected}")
    return LicenseGateResult("blocked" if enforce else "warning", detected, f"license-incompatible risk: {detected}")


def detect_license(project_path: str | Path) -> str:
    root = Path(project_path)
    for name in ("LICENSE", "LICENSE.md", "COPYING", "NOTICE"):
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")[:2000]
            return next((line.strip() for line in text.splitlines() if line.strip()), name)
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            license_value = json.loads(package_json.read_text(encoding="utf-8")).get("license")
        except (OSError, json.JSONDecodeError, AttributeError):
            license_value = ""
        if license_value:
            return str(license_value)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("license"):
                return line.split("=", 1)[-1].strip().strip('"').strip("'")
    return ""
