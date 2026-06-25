# scripts/dev/_archived

Archived ad-hoc developer scripts. **Nothing here is on any live code path, CI job, or import graph.**

Moved here on 2026-06-21 (P0 cleanup of `scripts/dev/`). These were one-off, machine-specific
throwaway scripts (many hardcode Windows paths such as `E:\FHD\XCAGI\...` and target an old
WeChat-DB analysis workflow), kept only for reference.

2026-06-25 second pass: archived 32 more orphan one-shots that had slipped into `scripts/` root
(the CI `guard_temp_scripts.py` only blocks repo-root + `scripts/*.py` one level, so these under
`FHD/scripts/` were never caught). All had zero references in workflows/imports/Makefiles/docs.

| dir | files | what it was |
|-----|------:|-------------|
| `analyze/`      | 32 | ad-hoc data/template/wechat-db analysis probes |
| `checks/`       | 48 | one-off "check_*" inspection scripts (DB/customer/units/templates probes) |
| `debug/`        |  4 | throwaway debug drivers |
| `fixes/`        | 13 | one-shot data-fix / force-sync / lane / manifest / surface-audit fixers |
| `tests_adhoc/`  | 59 | manual `test_*` / `final_*` drivers — NOT collected by pytest (`testpaths = ["tests"]`) |
| `tmp/`          |  3 | scratch text dumps |

Verified before archiving: no references from `.github/` workflows, `pyproject.toml`,
Makefiles/shell, or `scripts.dev.*` imports. Moved with `git mv` so history is preserved.

To restore one: `git mv scripts/dev/_archived/<dir> scripts/dev/<dir>`.
