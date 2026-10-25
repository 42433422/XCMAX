# XCMAX Harness Remediation Handoff — 2026-10-26

Timezone for local Mac timestamps: **Asia/Shanghai (UTC+8)**.

## Purpose
Handoff package for harness remediation (76-item checklist → eventual 1.0.0.7 macOS acceptance).  
No secrets, no `.env`, no customer DB dumps, no re-delete of materials.

## Upload repo
`https://github.com/42433422/XCMAX`  
Preferred branch for this package: `docs/handoff-harness-20261026`  
Mac path: `/Users/a4243342/XCMAX-runtime/agent-scratch/handoff-20261026/`  
Box path: `/workspace/handoff-20261026/`

## Inventory (items 1–12)

| # | Item | Status in package |
|---|------|-------------------|
| 1 | pasted-text-1.txt (必读附件) | **PRESENT** `must-read/pasted-text-1.txt` |
| 2 | checklist.json (76项完整) | **PRESENT** `must-read/checklist.json` |
| 3 | branch / HEAD / base main SHA | **PRESENT** `code/LOCATION.txt` |
| 4 | pushed branches / PR links | **PRESENT** `code/PR-AND-BRANCHES.txt` (draft branch itself is **unpushed**) |
| 5 | unpushed commits + uncommitted patches | **PRESENT** `patches/` |
| 6 | other AI/process warning | **PRESENT** `processes/WARNING.txt` |
| 7 | full 121 eval 33/88 report | **PRESENT** `eval-121/` |
| 8 | materials batch-delete case | **PRESENT** `materials-batch-delete/` (fixture/eval; not re-deleted) |
| 9 | Excel original 182 regression | **PRESENT** `excel-182/` |
|10 | net-deletion gate failure | **PRESENT** `net-deletion/` (baseline untouched) |
|11 | 1.0.0.7 update scope | **PRESENT** `release-1.0.0.7/SCOPE.json` |
|12 | build/upgrade/backup doc paths | **PRESENT** `release-1.0.0.7/existing-doc-paths.txt` |

## Code location (authoritative draft)
- Worktree: `/Users/a4243342/.codex/worktrees/b9cc/XCMAX`
- Branch: `codex/harness-remediation-20261025`
- HEAD: `9950a393b557b75e23098057ef4b7f81075e0647`
- Base / merge-base `origin/main`: `54d4541cbe4cd77e258163c75e3e9fc8c886b507`
- Ahead of main: **45 commits**, plus **uncommitted** Excel/workflow kernel migration files (see `code/uncommitted-status.txt`)
- Secondary checkout (unrelated): `/Users/a4243342/Desktop/XCMAX` on `fix/windows-delivery-closeout`

**Do not** `reset --hard`, clean, or force-push this worktree.

## SHA map
| Label | SHA |
|-------|-----|
| origin/main (observed) | `54d4541cbe4cd77e258163c75e3e9fc8c886b507` |
| draft HEAD (committed) | `9950a393b557b75e23098057ef4b7f81075e0647` |
| Excel 182 baseline HEAD | `d354ec5180f6c4d79c3716de953cad536dd829b6` |
| Installed Mac app (still 1.0.0.6) | `7e2f0e29ffd4edbd8fac1ca77409aa95e07d2c80` |
| PR #2675 merge (debt19 100%) | `54d4541cb…` (= current main) |

## Highlights for next owner
1. **121 offline eval**: 33 pass / 88 fail, `execution_mode=fixture_local` (not live model). Full JSON + itemized INDEX in `eval-121/`.
2. **materials_batch_delete_route_forces_agent_orchestrator**: **FAILED** in that report; independent post-delete readback still missing (TOOL-06).
3. **Excel**: original **182 passed** at `d354ec5180…`; kernel migration **uncommitted**; extended 576=566/10 still needs clean-HEAD对照; approval-input byte-binding gap open.
4. **Net deletion**: FAIL — baseline `2330609` unchanged; tip delta positive (~+5059 w/ untracked). Script: `FHD/scripts/dev/check_net_deletion.py`.
5. **1.0.0.7**: macOS-only acceptance; candidate/formal package/download/OTA/server **not** done; installed remains 1.0.0.6.

## Open gaps / not duplicated here
- Huge `harness-remediation-20261025/` evidence tree remains on Mac (including `clean-head-selected/` which may contain business site trees — **not** copied into this package).
- SQLite temp DBs under materials green-temp/red-temp **excluded**.
- Live provider model runs for QA-01 still outstanding per checklist.

## Patches apply hints
```bash
cd /path/to/XCMAX   # preferably from origin/main 54d4541c…
git am agent-scratch/handoff-20261026/patches/unpushed-commits/*.patch
# then
git apply agent-scratch/handoff-20261026/patches/uncommitted/including-new-files.diff
```
Uncommitted set may need manual conflict resolution if tree moved.

