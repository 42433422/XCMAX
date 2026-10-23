"""Build this employee with the shared xcagi-common build dependency."""

import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    source = parent / "packages" / "xcagi_common"
    if (source / "xcagi_common" / "employee_pack.py").is_file():
        sys.path.insert(0, str(source))
        break

from xcagi_common.employee_pack import build_employee_pack


def main() -> None:
    build_employee_pack(
        Path(__file__).resolve().parent,
        pack_id="trademark-generation-employee",
        backend_suffixes=[".py"],
        extra_files=["README.md", "rule_spec.json", "asset_manifest.json"],
    )


if __name__ == "__main__":
    main()
