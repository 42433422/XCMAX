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
    print(
        build_employee_pack(
            Path(__file__).resolve().parent,
            pack_id="csv-generate-employee",
            backend_suffixes=[".py", ".xlsx", ".xlsm", ".xls"],
            extra_files=["README.md"],
        )
    )


if __name__ == "__main__":
    main()
