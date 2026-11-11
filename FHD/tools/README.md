# Tools Directory

`tools/` is the only place for operational and temporary scripts that are still active.

## Maintained tools

- `tools/mod_pack.py`: package, inspect, sign and validate Mods; run `python tools/mod_pack.py --help` from `FHD/`. Validation uses the runtime signature policy.
- `tools/validate_performance.py`: component diagnostics and local microbenchmarks; its process counters do not establish online service performance.
- `tools/bartender-monitor/`: standalone Windows BarTender OCR and mapping tool.
- `tools/debug/` and `tools/wechat_sync/`: diagnostics and WeChat synchronization.
- `tools/XcagiDownloader/`, `tools/XcagiInstaller/` and `tools/XcagiInstaller.Tests/`: Windows delivery tools and their tests.
- `tools/templates/`: reusable script templates.

## Rules

- New temporary scripts must be created under `tools/`, not business directories.
- Historical one-off scripts are archived outside the workspace; see the repository `ARCHIVE_POINTER.md`.
- Prefer CLI scripts with explicit arguments and `--dry-run` support.
- Print a short result summary at the end.

## How to Start a New Script

1. Copy `tools/templates/script_template.py`.
2. Place it beside the maintained tool it supports.
3. Implement the `run()` function and keep the CLI contract.
