"""Path boundary for customer-data build and publication tooling."""

from pathlib import Path


def private_path(value: Path | None, label: str) -> Path:
    if value is None:
        raise ValueError(f"{label} must explicitly name an external private directory")
    path = Path(value).expanduser().resolve()
    if any(_git_checkout(parent) for parent in (path, *path.parents)):
        raise ValueError(f"{label} must be outside a Git checkout")
    return path


def _git_checkout(path: Path) -> bool:
    marker = path / ".git"
    if marker.is_dir():
        return (marker / "HEAD").is_file()
    return marker.is_file() and marker.read_text(encoding="utf-8").startswith(
        "gitdir: "
    )
