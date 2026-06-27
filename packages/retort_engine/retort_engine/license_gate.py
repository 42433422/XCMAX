from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_LICENSES = ("MIT", "Apache", "BSD", "ISC", "Python")


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


def license_gate(project_path: str | Path, *, enforce: bool = False, allowed: tuple[str, ...] = DEFAULT_ALLOWED_LICENSES) -> LicenseGateResult:
    detected = detect_license(project_path)
    if not detected:
        return LicenseGateResult("blocked" if enforce else "warning", "", "license-incompatible risk: no LICENSE file detected")
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
    return ""
