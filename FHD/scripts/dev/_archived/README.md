# scripts/dev/_archived

Archived ad-hoc developer scripts. **Nothing here is on any live code path, CI job, or import graph.**

Moved here on 2026-06-21 (P0 cleanup of `scripts/dev/`). These were one-off, machine-specific
throwaway scripts (many hardcode Windows paths such as `E:\FHD\XCAGI\...` and target an old
WeChat-DB analysis workflow), kept only for reference.

| dir | files | what it was |
|-----|------:|-------------|
| `analyze/`      | 32 | ad-hoc data/template/wechat-db analysis probes |
| `checks/`       | 30 | one-off "check_*" inspection scripts |
| `debug/`        |  4 | throwaway debug drivers |
| `fixes/`        |  5 | one-shot data-fix / force-sync scripts |
| `tests_adhoc/`  | 53 | manual `test_*` drivers — NOT collected by pytest (`testpaths = ["tests"]`) |
| `tmp/`          |  3 | scratch text dumps |

Verified before archiving: no references from `.github/` workflows, `pyproject.toml`,
Makefiles/shell, or `scripts.dev.*` imports. Moved with `git mv` so history is preserved.

To restore one: `git mv scripts/dev/_archived/<dir> scripts/dev/<dir>`.
